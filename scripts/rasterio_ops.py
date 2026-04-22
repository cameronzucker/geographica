"""Rasterio-based replacements for GDAL CLI tools.

Eliminates the system GDAL install dependency — rasterio ships pre-built
wheels with GDAL bundled. All pipeline scripts should call these functions
instead of subprocess.run(["gdal_translate", ...]) etc.

Operations provided:
  - filter_tiles_by_bbox: ogr2ogr spatial filter → shapely + dbfread/pyshp
  - check_jp2_support: gdalinfo --formats → rasterio.drivers()
  - reproject_to_mercator: gdalwarp -t_srs EPSG:3857 → rasterio.warp
  - merge_to_mbtiles: gdalbuildvrt + gdal_translate → rasterio.merge + SQLite
  - translate_to_mbtiles: gdal_translate -of MBTiles → rasterio + SQLite
  - build_overviews: gdaladdo -r average → rasterio.build_overviews
  - translate_format: gdal_translate -of GTiff → rasterio copy
"""

import io
import logging
import math
import os
import sqlite3
import struct
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.merge import merge as rasterio_merge
from rasterio.transform import from_bounds
from rasterio.warp import calculate_default_transform, reproject

log = logging.getLogger(__name__)

WEB_MERCATOR = CRS.from_epsg(3857)
TILE_SIZE = 256

# ---------------------------------------------------------------------------
# MBTiles helpers
# ---------------------------------------------------------------------------

def _init_mbtiles(db_path: Path, metadata: dict | None = None) -> sqlite3.Connection:
    """Create or open an MBTiles SQLite database with the correct schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tiles (
            zoom_level INTEGER,
            tile_column INTEGER,
            tile_row INTEGER,
            tile_data BLOB,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metadata (
            name TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    if metadata:
        for k, v in metadata.items():
            conn.execute(
                "INSERT OR REPLACE INTO metadata (name, value) VALUES (?, ?)",
                (k, str(v)),
            )
    conn.commit()
    return conn


def _tile_bounds(x: int, y: int, z: int) -> tuple[float, float, float, float]:
    """Return (west, south, east, north) in EPSG:3857 for a slippy-map tile.

    Uses top-origin Y convention (y=0 at north pole), matching _lonlat_to_tile.
    """
    n = 2 ** z
    origin = 20037508.342789244
    tile_size = 2 * origin / n
    west = -origin + x * tile_size
    east = west + tile_size
    # Slippy map y-origin is top (north pole)
    north = origin - y * tile_size
    south = north - tile_size
    return (west, south, east, north)


def _encode_jpeg(array: np.ndarray, quality: int = 85) -> bytes:
    """Encode a 3-band uint8 array as JPEG bytes using rasterio's memory driver."""
    with rasterio.MemoryFile() as memfile:
        with memfile.open(
            driver="JPEG",
            height=array.shape[1],
            width=array.shape[2],
            count=min(array.shape[0], 3),  # JPEG supports 1 or 3 bands
            dtype="uint8",
            quality=quality,
        ) as dst:
            dst.write(array[:3])  # Only write RGB bands
        return memfile.read()


def _encode_png(array: np.ndarray) -> bytes:
    """Encode a uint8 array as PNG bytes using rasterio's memory driver."""
    with rasterio.MemoryFile() as memfile:
        with memfile.open(
            driver="PNG",
            height=array.shape[1],
            width=array.shape[2],
            count=array.shape[0],
            dtype="uint8",
        ) as dst:
            dst.write(array)
        return memfile.read()


# ---------------------------------------------------------------------------
# 1. Spatial filter (replaces ogr2ogr -spat)
# ---------------------------------------------------------------------------

def filter_tiles_by_bbox(
    shapefile_path: Path,
    west: float, south: float, east: float, north: float,
) -> list[str]:
    """Spatially filter a tile index shapefile by bounding box.

    Replaces: ogr2ogr -f CSV /vsistdout/ <shp> -spat w s e n -select filename

    Uses fiona (ships with rasterio wheel) to read the shapefile and
    shapely for bbox intersection. Falls back to simple DBF parsing
    if fiona is unavailable.
    """
    from shapely.geometry import box, shape as shapely_shape

    bbox_geom = box(west, south, east, north)
    filenames = []

    try:
        import fiona
        with fiona.open(str(shapefile_path)) as src:
            for feature in src:
                geom = shapely_shape(feature["geometry"])
                if geom.intersects(bbox_geom):
                    props = feature["properties"]
                    fname = props.get("filename") or props.get("FILENAME") or props.get("location")
                    if fname:
                        filenames.append(fname)
    except ImportError:
        # Fallback: use pyshp if fiona not available
        import shapefile
        with shapefile.Reader(str(shapefile_path)) as sf:
            # Find the filename field
            field_names = [f[0].lower() for f in sf.fields[1:]]
            fname_idx = None
            for i, name in enumerate(field_names):
                if name in ("filename", "location"):
                    fname_idx = i
                    break

            if fname_idx is None:
                log.error("No 'filename' or 'location' field in shapefile")
                return []

            for shape_rec in sf.iterShapeRecords():
                geom = shapely_shape(shape_rec.shape.__geo_interface__)
                if geom.intersects(bbox_geom):
                    filenames.append(shape_rec.record[fname_idx])

    log.info("Spatial filter: %d tiles intersect bbox", len(filenames))
    return filenames


# ---------------------------------------------------------------------------
# 2. Driver/format check (replaces gdalinfo --formats)
# ---------------------------------------------------------------------------

def check_jp2_support() -> bool:
    """Check if rasterio/GDAL supports JP2OpenJPEG format.

    Replaces: gdalinfo --formats | grep JP2OpenJPEG
    """
    try:
        drivers = rasterio.drivers.raster_driver_extensions()
        return "jp2" in drivers
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 3. Reproject to Web Mercator (replaces gdalwarp)
# ---------------------------------------------------------------------------

def reproject_to_mercator(
    src_path: Path,
    dst_path: Path,
    resampling: str = "lanczos",
    compress: str = "deflate",
    cancel_check=None,
) -> bool:
    """Reproject a raster to EPSG:3857 with tiled GeoTIFF output.

    Replaces: gdalwarp -t_srs EPSG:3857 -r lanczos -co TILED=YES
              -co COMPRESS=DEFLATE <src> <dst>
    """
    resamp = getattr(Resampling, resampling, Resampling.lanczos)
    t0 = time.monotonic()

    try:
        with rasterio.open(str(src_path)) as src:
            if cancel_check and cancel_check():
                return False

            transform, width, height = calculate_default_transform(
                src.crs, WEB_MERCATOR, src.width, src.height, *src.bounds
            )

            profile = src.profile.copy()
            profile.update(
                crs=WEB_MERCATOR,
                transform=transform,
                width=width,
                height=height,
                driver="GTiff",
                tiled=True,
                compress=compress,
                blockxsize=256,
                blockysize=256,
            )

            dst_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(str(dst_path), "w", **profile) as dst:
                for i in range(1, src.count + 1):
                    if cancel_check and cancel_check():
                        return False
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=WEB_MERCATOR,
                        resampling=resamp,
                        # Use 1 GDAL internal thread per reproject call.
                    # The pipeline already parallelizes via ThreadPoolExecutor
                    # (4 workers). With num_threads=cpu_count, each worker spawns
                    # 4 GDAL threads → 16 total on 4 cores → thrashing.
                    num_threads=1,
                    )

            # B3 fix: capture dataset attributes BEFORE the `with` exits.
            # log.debug eagerly evaluates its arguments regardless of log level,
            # so accessing src.width / src.height after exit would raise under
            # stricter rasterio versions and return False via the enclosing except.
            src_width = src.width
            src_height = src.height
        elapsed = time.monotonic() - t0
        log.debug("Reproject %s: %dx%d → %dx%d in %.1fs",
                  src_path.name, src_width, src_height, width, height, elapsed)
        return True

    except Exception as exc:
        log.error("Reproject failed for %s: %s", src_path.name, exc)
        if dst_path.exists():
            dst_path.unlink()
        return False


# ---------------------------------------------------------------------------
# 4. Translate single raster to different format (replaces gdal_translate)
# ---------------------------------------------------------------------------

def translate_format(
    src_path: Path,
    dst_path: Path,
    output_format: str = "GTiff",
    creation_options: dict | None = None,
) -> bool:
    """Convert a raster from one format to another.

    Replaces: gdal_translate -of <format> [-co KEY=VAL ...] <src> <dst>
    Common use: JP2 → GeoTIFF conversion for NAIP data.
    """
    if creation_options is None:
        creation_options = {"tiled": True, "compress": "deflate"}

    try:
        with rasterio.open(str(src_path)) as src:
            profile = src.profile.copy()
            profile.update(driver=output_format, **creation_options)

            dst_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(str(dst_path), "w", **profile) as dst:
                # Copy in blocks for memory efficiency
                for ji, window in src.block_windows(1):
                    data = src.read(window=window)
                    dst.write(data, window=window)
        return True

    except Exception as exc:
        log.error("Format translation failed for %s: %s", src_path.name, exc)
        if dst_path.exists():
            dst_path.unlink()
        return False


# ---------------------------------------------------------------------------
# 5. Merge rasters and write to MBTiles (replaces gdalbuildvrt + gdal_translate)
# ---------------------------------------------------------------------------

def merge_to_mbtiles(
    input_paths: list[Path],
    output_path: Path,
    tile_format: str = "jpeg",
    quality: int = 85,
    cancel_check=None,
) -> bool:
    """Merge multiple rasters into an MBTiles file.

    Replaces: gdalbuildvrt <vrt> <files...> && gdal_translate -of MBTiles <vrt> <out>

    Renders tiles to the filesystem first (no lock contention), then
    bulk-imports into MBTiles in a single fast pass.
    """
    if not input_paths:
        log.error("No input files to merge")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    tile_dir = output_path.parent / f".tiles_{output_path.stem}"

    try:
        # Open all datasets
        datasets = [rasterio.open(str(p)) for p in input_paths]

        try:
            # Single-file fast path: read directly, skip rasterio_merge overhead.
            # rasterio_merge creates a full in-memory mosaic (~1.5-3 GB for a
            # 486 MB GeoTIFF) which is unnecessary when there's only one input.
            if len(datasets) == 1:
                ds = datasets[0]
                mosaic = ds.read()
                mosaic_transform = ds.transform
            else:
                mosaic, mosaic_transform = rasterio_merge(datasets)

            if cancel_check and cancel_check():
                return False

            first_crs = datasets[0].crs
            min_zoom, max_zoom = _compute_zoom_range(mosaic_transform, first_crs)

            from rasterio.warp import transform_bounds
            bounds_4326 = transform_bounds(first_crs, CRS.from_epsg(4326), *datasets[0].bounds)
            for ds in datasets[1:]:
                b = transform_bounds(ds.crs, CRS.from_epsg(4326), *ds.bounds)
                bounds_4326 = (
                    min(bounds_4326[0], b[0]), min(bounds_4326[1], b[1]),
                    max(bounds_4326[2], b[2]), max(bounds_4326[3], b[3]),
                )

            # Close datasets early — no longer needed after extracting
            # CRS, transform, bounds, and mosaic data.
            for d in datasets:
                d.close()
            datasets = []

            # Stage 1: render tiles to filesystem (no SQLite lock)
            tile_dir.mkdir(parents=True, exist_ok=True)

            encode_fn = _encode_jpeg if tile_format.lower() == "jpeg" else _encode_png
            t_render = time.monotonic()
            tile_count = _rasterize_to_disk(
                mosaic, mosaic_transform, first_crs,
                tile_dir, min_zoom, max_zoom,
                encode_fn, quality, cancel_check,
            )
            render_elapsed = time.monotonic() - t_render
            log.debug("Tile rendering: %d tiles in %.1fs (%.0f tiles/sec)",
                      tile_count, render_elapsed,
                      tile_count / render_elapsed if render_elapsed > 0 else 0)

            if cancel_check and cancel_check():
                return False

            # Release the mosaic array before bulk import.
            del mosaic
            import gc
            gc.collect()
            try:
                import ctypes
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass

            # Stage 2: bulk import from filesystem to MBTiles
            if tile_count > 0:
                t_import = time.monotonic()
                _bulk_import_tiles(
                    tile_dir, output_path, tile_format,
                    min_zoom, max_zoom, bounds_4326,
                )
                import_elapsed = time.monotonic() - t_import
                log.debug("Bulk import: %d tiles in %.1fs (%.0f tiles/sec)",
                          tile_count, import_elapsed,
                          tile_count / import_elapsed if import_elapsed > 0 else 0)

        finally:
            for ds in datasets:
                ds.close()
            # Always clean up tile directory, even on exception/cancel
            _cleanup_tile_dir(tile_dir)

        return True

    except Exception as exc:
        log.error("merge_to_mbtiles failed: %s", exc)
        _cleanup_tile_dir(tile_dir)
        return False


def translate_to_mbtiles(
    src_path: Path,
    output_path: Path,
    tile_format: str = "jpeg",
    quality: int = 85,
    cancel_check=None,
) -> bool:
    """Convert a single raster to MBTiles.

    Replaces: gdal_translate -of MBTiles -co TILE_FORMAT=JPEG <src> <out>
    """
    return merge_to_mbtiles([src_path], output_path, tile_format, quality, cancel_check)


def _compute_zoom_range(transform, crs) -> tuple[int, int]:
    """Compute min/max zoom from raster resolution."""
    res_x = abs(transform.a)
    if crs == WEB_MERCATOR:
        max_zoom = max(0, int(math.log2(20037508.342789244 * 2 / (TILE_SIZE * res_x))))
    else:
        res_meters = res_x * 111320
        max_zoom = max(0, int(math.log2(20037508.342789244 * 2 / (TILE_SIZE * res_meters))))
    min_zoom = max(0, max_zoom - 4)
    return min_zoom, max_zoom


def _rasterize_to_disk(
    data: np.ndarray,
    transform,
    src_crs,
    tile_dir: Path,
    min_zoom: int,
    max_zoom: int,
    encode_fn,
    quality: int,
    cancel_check=None,
) -> int:
    """Render raster into {z}/{x}/{y}.{ext} tile files on the filesystem.

    No database involved — fully parallelizable, zero lock contention.
    Returns the number of tiles written.
    """
    from rasterio.warp import transform_bounds

    left = transform.c
    top = transform.f
    right = left + transform.a * data.shape[2]
    bottom = top + transform.e * data.shape[1]
    bounds_4326 = transform_bounds(src_crs, CRS.from_epsg(4326), left, bottom, right, top)

    tile_count = 0
    for zoom in range(min_zoom, max_zoom + 1):
        if cancel_check and cancel_check():
            return tile_count

        x_min, y_min = _lonlat_to_tile(bounds_4326[0], bounds_4326[3], zoom)
        x_max, y_max = _lonlat_to_tile(bounds_4326[2], bounds_4326[1], zoom)

        for tx in range(x_min, x_max + 1):
            for ty in range(y_min, y_max + 1):
                if cancel_check and cancel_check():
                    return tile_count

                tile_bounds_3857 = _tile_bounds(tx, ty, zoom)
                tile_bounds_src = transform_bounds(
                    WEB_MERCATOR, src_crs, *tile_bounds_3857,
                )

                tile_data = _read_tile_from_array(
                    data, transform, tile_bounds_src, TILE_SIZE,
                )

                if tile_data is None or _is_empty_tile(tile_data):
                    continue

                tile_bytes = encode_fn(tile_data, quality) if encode_fn == _encode_jpeg else encode_fn(tile_data)

                # TMS y-flip
                tms_y = (2 ** zoom - 1) - ty

                # Write to {z}/{x}/{y}.tile
                z_dir = tile_dir / str(zoom) / str(tx)
                z_dir.mkdir(parents=True, exist_ok=True)
                (z_dir / f"{tms_y}.tile").write_bytes(tile_bytes)
                tile_count += 1

                if tile_count % 1000 == 0:
                    log.info("Rendered %d tiles to disk (zoom %d)", tile_count, zoom)

    log.info("Total tiles rendered to disk: %d", tile_count)
    return tile_count


def _bulk_import_tiles(
    tile_dir: Path,
    output_path: Path,
    tile_format: str,
    min_zoom: int,
    max_zoom: int,
    bounds_4326: tuple[float, float, float, float],
) -> None:
    """Bulk-import tile files from filesystem into MBTiles SQLite.

    Single sequential scan — reads tile files and inserts in large transactions.
    Much faster than one-at-a-time INSERT during concurrent processing.
    """
    conn = _init_mbtiles(output_path, {
        "name": output_path.stem,
        "format": tile_format.lower(),
        "type": "overlay",
        "minzoom": str(min_zoom),
        "maxzoom": str(max_zoom),
        "bounds": f"{bounds_4326[0]},{bounds_4326[1]},{bounds_4326[2]},{bounds_4326[3]}",
    })

    tile_count = 0
    try:
        # Walk the {z}/{x}/{y}.tile directory structure
        for z_dir in sorted(tile_dir.iterdir()):
            if not z_dir.is_dir():
                continue
            zoom = int(z_dir.name)
            for x_dir in sorted(z_dir.iterdir()):
                if not x_dir.is_dir():
                    continue
                tx = int(x_dir.name)
                for tile_file in x_dir.iterdir():
                    if not tile_file.suffix == ".tile":
                        continue
                    tms_y = int(tile_file.stem)
                    tile_bytes = tile_file.read_bytes()

                    conn.execute(
                        "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                        (zoom, tx, tms_y, tile_bytes),
                    )
                    tile_count += 1

                    if tile_count % 5000 == 0:
                        conn.commit()
                        log.info("Imported %d tiles into MBTiles (zoom %d)", tile_count, zoom)

        conn.commit()
        log.info("Bulk import complete: %d tiles", tile_count)
    finally:
        conn.close()


def _cleanup_tile_dir(tile_dir: Path) -> None:
    """Remove the temporary tile directory."""
    import shutil
    try:
        shutil.rmtree(tile_dir, ignore_errors=True)
    except Exception:
        pass


def _lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    """Convert lon/lat to tile coordinates at given zoom."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def _read_tile_from_array(
    data: np.ndarray,
    transform,
    tile_bounds: tuple[float, float, float, float],
    tile_size: int,
) -> np.ndarray | None:
    """Extract a tile-sized portion from a numpy array given geographic bounds.

    For edge tiles that extend beyond the source array, the valid portion is
    placed at the correct offset within the output tile (rest stays black).
    """
    from rasterio.transform import rowcol

    west, south, east, north = tile_bounds
    try:
        raw_row_start, raw_col_start = rowcol(transform, west, north)
        raw_row_end, raw_col_end = rowcol(transform, east, south)
    except Exception:
        return None

    # Full tile span in source pixels (before clamping)
    full_row_span = raw_row_end - raw_row_start
    full_col_span = raw_col_end - raw_col_start
    if full_row_span <= 0 or full_col_span <= 0:
        return None

    # B4 fix: reject tiles whose pixel range is entirely outside the source array.
    # Without this guard, the clamps below pin row_start/col_start to the array
    # edge but the dst_row_start arithmetic at 626-629 produces negative indices,
    # which numpy slices legally from the end — stamping real pixels at wrong coords.
    if raw_row_end <= 0 or raw_row_start >= data.shape[1]:
        return None
    if raw_col_end <= 0 or raw_col_start >= data.shape[2]:
        return None

    # Clamp to array bounds
    row_start = max(0, min(data.shape[1] - 1, raw_row_start))
    row_end = max(0, min(data.shape[1], raw_row_end))
    col_start = max(0, min(data.shape[2] - 1, raw_col_start))
    col_end = max(0, min(data.shape[2], raw_col_end))

    if row_end <= row_start or col_end <= col_start:
        return None

    window_data = data[:, row_start:row_end, col_start:col_end]

    if window_data.size == 0:
        return None

    # Compute destination region within the tile for edge tiles
    # (tiles that extend beyond the source array)
    dst_row_start = int((row_start - raw_row_start) / full_row_span * tile_size)
    dst_col_start = int((col_start - raw_col_start) / full_col_span * tile_size)
    dst_row_end = int((row_end - raw_row_start) / full_row_span * tile_size)
    dst_col_end = int((col_end - raw_col_start) / full_col_span * tile_size)

    dst_h = max(1, dst_row_end - dst_row_start)
    dst_w = max(1, dst_col_end - dst_col_start)

    # Resize valid window to the destination region size
    src_rows = np.minimum(
        (np.arange(dst_h) * (window_data.shape[1] / dst_h)).astype(np.intp),
        window_data.shape[1] - 1,
    )
    src_cols = np.minimum(
        (np.arange(dst_w) * (window_data.shape[2] / dst_w)).astype(np.intp),
        window_data.shape[2] - 1,
    )
    resized = window_data[:, src_rows, :][:, :, src_cols]

    # Place into output tile at the correct offset
    bands = data.shape[0]
    tile = np.zeros((bands, tile_size, tile_size), dtype=data.dtype)
    tile[:, dst_row_start:dst_row_start + dst_h, dst_col_start:dst_col_start + dst_w] = resized

    return tile.astype(np.uint8) if tile.dtype != np.uint8 else tile


def _is_empty_tile(data: np.ndarray) -> bool:
    """Check if a tile is all zeros/black (no actual data)."""
    return not np.any(data)


def _init_journal(conn: sqlite3.Connection) -> None:
    """Create the _overview_work_queue dirty-ancestor journal table if missing.

    Idempotent. Safe to call on any MBTiles connection, including legacy
    files that pre-date the journal design. Part of the 2026-04-22
    incremental-pyramid fix — see
    docs/superpowers/specs/2026-04-22-overview-incremental-design.md §Migration.

    Transaction contract: this helper issues DDL only, which auto-commits
    in SQLite's default isolation mode. Callers own their transactions —
    do NOT call this INSIDE a BEGIN block; call it before opening the
    transaction. See Task 8's merge_mbtiles for the pattern.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS _overview_work_queue (
            zoom_level   INTEGER NOT NULL,
            tile_column  INTEGER NOT NULL,
            tile_row     INTEGER NOT NULL,
            PRIMARY KEY (zoom_level, tile_column, tile_row)
        )
        """
    )


def _enqueue_ancestors(
    conn: sqlite3.Connection,
    base_tiles: list[tuple[int, int, int]],
) -> None:
    """Enqueue the full ancestor lineage for each base tile into the journal.

    For each (z, tc, tr) with z >= 1, inserts (z-1, tc>>1, tr>>1),
    (z-2, tc>>2, tr>>2), ..., (0, 0, 0) into _overview_work_queue with
    INSERT OR IGNORE (the PK on (zoom, tc, tr) collapses duplicates so
    repeated calls are idempotent). Base tiles already at z=0 produce
    no rows — they have no ancestors.

    Caller is responsible for:
    - Having called _init_journal(conn) first.
    - Calling conn.commit() afterward (this function does not commit so that
      callers can wrap mutation+enqueue in one atomic transaction — see spec
      §Cross-statement atomicity).
    """
    if not base_tiles:
        return
    rows = []
    for z, tc, tr in base_tiles:
        for dz in range(1, z + 1):
            rows.append((z - dz, tc >> dz, tr >> dz))
    conn.executemany(
        "INSERT OR IGNORE INTO _overview_work_queue "
        "(zoom_level, tile_column, tile_row) VALUES (?, ?, ?)",
        rows,
    )


def _mutate_base_tile(
    conn: sqlite3.Connection,
    action: str,  # "upsert" | "delete"
    z: int,
    tc: int,
    tr: int,
    tile_data: bytes | None = None,
) -> None:
    """Atomic single-tile mutation + ancestor enqueue.

    Combines the tile write and the journal enqueue into the same logical
    transaction. If the caller has an open transaction, this function does
    NOT open a new one (so the caller's commit/rollback covers both
    operations). If no transaction is open, the default sqlite3 auto-commit
    still serializes the two statements within one connection — but callers
    should prefer wrapping multiple _mutate_base_tile calls in an explicit
    BEGIN/COMMIT for efficiency.

    action='upsert' uses INSERT OR REPLACE with tile_data.
    action='delete' removes the tile; tile_data is ignored.
    """
    if action not in ("upsert", "delete"):
        raise ValueError(f"unknown action: {action!r}")
    if action == "upsert":
        if tile_data is None:
            raise ValueError("tile_data is required for upsert")
        conn.execute(
            "INSERT OR REPLACE INTO tiles "
            "(zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
            (z, tc, tr, tile_data),
        )
    else:  # delete
        conn.execute(
            "DELETE FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, tc, tr),
        )
    _enqueue_ancestors(conn, [(z, tc, tr)])


# ---------------------------------------------------------------------------
# 6. Build overview pyramids (replaces gdaladdo)
# ---------------------------------------------------------------------------

def build_overviews(
    mbtiles_path: Path,
    levels: list[int] | None = None,
    resampling: str = "average",
    cancel_check=None,
) -> bool:
    """Build overview pyramid for an MBTiles file by downsampling existing tiles.

    Replaces: gdaladdo -r average <mbtiles> 2 4 8 16

    Works directly on the MBTiles SQLite database: reads tiles at the highest
    zoom, composites 2x2 groups into the next lower zoom, repeating until
    the minimum zoom is reached.
    """
    if levels is None:
        levels = [2, 4, 8, 16]

    conn = None
    try:
        conn = sqlite3.connect(str(mbtiles_path))
        conn.execute("PRAGMA journal_mode=WAL")

        # Find current max zoom (base tiles)
        row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
        if not row or row[0] is None:
            log.warning("No tiles in %s — skipping overviews", mbtiles_path)
            return True

        max_zoom = row[0]

        # Delete existing overview tiles so stale overviews don't persist
        # after new quads are merged. Only delete below max_zoom (base tiles
        # are never touched).
        deleted = conn.execute(
            "DELETE FROM tiles WHERE zoom_level < ?", (max_zoom,)
        ).rowcount
        if deleted:
            conn.commit()
            log.info("Cleared %d stale overview tiles before rebuild", deleted)

        # Build: for each zoom from max_zoom-1 down, composite 2x2 blocks
        for z in range(max_zoom - 1, -1, -1):
            if cancel_check and cancel_check():
                return False

            parent_z = z + 1
            rows = conn.execute(
                "SELECT DISTINCT tile_column/2, tile_row/2 FROM tiles WHERE zoom_level = ?",
                (parent_z,),
            ).fetchall()

            if not rows:
                break

            tile_count = 0
            for (tx, ty) in rows:
                # Gather 2x2 child tiles
                children = []
                for dx in range(2):
                    for dy in range(2):
                        child = conn.execute(
                            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                            (parent_z, tx * 2 + dx, ty * 2 + dy),
                        ).fetchone()
                        children.append((dx, dy, child[0] if child else None))

                # Only create overview when ALL 4 children exist.
                # Partial 2x2 blocks produce black quadrants in JPEG.
                if not all(c[2] for c in children):
                    continue

                # Decode children, downsample with true 2x2 averaging, composite
                composite = np.zeros((3, TILE_SIZE, TILE_SIZE), dtype=np.uint8)
                half = TILE_SIZE // 2

                for dx, dy, tile_data in children:
                    if tile_data is None:
                        continue
                    try:
                        with rasterio.MemoryFile(tile_data) as memfile:
                            with memfile.open() as ds:
                                bands = min(ds.count, 3)
                                tile_arr = ds.read(list(range(1, bands + 1)))
                                # True 2x2 box averaging (not stride-2 subsampling)
                                h_src, w_src = tile_arr.shape[1], tile_arr.shape[2]
                                if h_src >= 2 and w_src >= 2:
                                    # Reshape to (bands, h/2, 2, w/2, 2) then mean over axes 2,4
                                    h2 = (h_src // 2) * 2
                                    w2 = (w_src // 2) * 2
                                    cropped = tile_arr[:, :h2, :w2].astype(np.uint16)
                                    small = cropped.reshape(bands, h2 // 2, 2, w2 // 2, 2).mean(axis=(2, 4)).astype(np.uint8)
                                    small = small[:, :half, :half]
                                else:
                                    small = tile_arr[:, :half, :half]
                                x_off = dx * half
                                # TMS: dy=0 is south, dy=1 is north
                                # Image: y=0 is top (north)
                                y_off = (1 - dy) * half
                                h = min(small.shape[1], half)
                                w = min(small.shape[2], half)
                                composite[:bands, y_off:y_off + h, x_off:x_off + w] = small[:, :h, :w]
                    except Exception:
                        continue

                tile_bytes = _encode_jpeg(composite)
                conn.execute(
                    "INSERT OR REPLACE INTO tiles (zoom_level, tile_column, tile_row, tile_data) VALUES (?, ?, ?, ?)",
                    (z, tx, ty, tile_bytes),
                )
                tile_count += 1

            conn.commit()
            if tile_count > 0:
                log.info("Built %d overview tiles at zoom %d", tile_count, z)

        # Update metadata
        min_zoom = conn.execute("SELECT MIN(zoom_level) FROM tiles").fetchone()[0]
        max_zoom_actual = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES ('minzoom', ?)", (str(min_zoom),))
        conn.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES ('maxzoom', ?)", (str(max_zoom_actual),))
        conn.commit()

        log.info("Overviews complete for %s (zoom %d-%d)", mbtiles_path, min_zoom, max_zoom_actual)
        return True

    except Exception as exc:
        log.error("build_overviews failed for %s: %s", mbtiles_path, exc)
        return False
    finally:
        if conn:
            conn.close()


def inpaint_nodata_pixels(
    mbtiles_path: Path,
    nodata_threshold: int = 20,
    max_nodata_ratio: float = 0.5,
    cancel_check=None,
) -> int:
    """Replace near-black (nodata) pixels with nearest valid imagery.

    JPEG tiles have no alpha channel, so nodata renders as opaque black —
    visible as dark seams at NAIP quad boundaries and thin strips at data
    edges. This function fills every near-black pixel with the color of its
    nearest non-black neighbor using a distance transform, eliminating
    visible seams without losing any real imagery.

    Skips tiles that are fully valid (no work needed) or mostly empty
    (>max_nodata_ratio black — these are boundary tiles better handled
    by erode_nodata_edges).

    Returns the number of tiles modified.
    """
    from scipy.ndimage import distance_transform_edt

    conn = sqlite3.connect(str(mbtiles_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")

        # Stream tiles via cursor iteration instead of fetchall() to avoid
        # loading all tile BLOBs into memory at once (OOM at scale).
        cursor = conn.execute(
            "SELECT zoom_level, tile_column, tile_row, tile_data FROM tiles"
        )

        fixed = 0
        batch = cursor.fetchmany(500)
        while batch:
            if cancel_check and cancel_check():
                log.info("inpaint_nodata_pixels: cancellation requested, stopping after %d tiles", fixed)
                break
            for z, x, y, data in batch:
                with rasterio.MemoryFile(data) as mf:
                    with mf.open() as ds:
                        arr = ds.read().copy()

                black = np.all(arr[:3] <= nodata_threshold, axis=0)
                n_black = black.sum()
                total = arr.shape[1] * arr.shape[2]

                if n_black == 0 or n_black > total * max_nodata_ratio:
                    continue

                _, nearest = distance_transform_edt(
                    black, return_distances=True, return_indices=True,
                )
                for band in range(arr.shape[0]):
                    arr[band][black] = arr[band][nearest[0][black], nearest[1][black]]

                conn.execute(
                    "UPDATE tiles SET tile_data=? "
                    "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                    (_encode_jpeg(arr), z, x, y),
                )
                fixed += 1

                if fixed % 1000 == 0:
                    conn.commit()
                    log.info("Inpainted %d tiles so far", fixed)

            batch = cursor.fetchmany(500)

        conn.commit()
        if fixed:
            log.info("Inpainted %d tiles in %s", fixed, mbtiles_path)
        return fixed
    finally:
        conn.close()


def erode_nodata_edges(
    mbtiles_path: Path,
    edge_pixels: int = 48,
    min_edge_fill: float = 0.90,
    nodata_threshold: int = 20,
    cancel_check=None,
) -> int:
    """Remove boundary tiles with significant nodata (black) at edges.

    Iteratively strips the outer ring of tiles until all remaining boundary
    tiles have at least `min_edge_fill` imagery in every edge strip.
    JPEG tiles have no transparency, so partial tiles at data boundaries
    render as black rectangles over the basemap. This function erodes those
    away so the basemap shows through cleanly.

    Returns the total number of tiles removed.
    """
    conn = sqlite3.connect(str(mbtiles_path))
    try:
        total_removed = 0

        # Only erode at the base (max) zoom level. Overviews are rebuilt
        # from post-erosion tiles, so eroding at overview zooms independently
        # would create zoom-level coverage gaps (overview eroded while
        # children survive → basemap at low zoom, imagery at high zoom).
        max_z_row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
        if not max_z_row or max_z_row[0] is None:
            return 0
        zoom_levels = [max_z_row[0]]

        for z in zoom_levels:
            removed_this_round = 1  # seed the loop
            while removed_this_round > 0:
                if cancel_check and cancel_check():
                    log.info("erode_nodata_edges: cancellation requested, stopping after %d tiles", total_removed)
                    return total_removed
                removed_this_round = 0
                # Get current boundary tile positions
                bounds = conn.execute(
                    "SELECT MIN(tile_column), MAX(tile_column), "
                    "MIN(tile_row), MAX(tile_row) FROM tiles WHERE zoom_level=?",
                    (z,),
                ).fetchone()
                if bounds[0] is None:
                    break
                min_col, max_col, min_row, max_row = bounds

                boundary = conn.execute(
                    "SELECT tile_column, tile_row, tile_data FROM tiles "
                    "WHERE zoom_level=? AND ("
                    "  tile_column=? OR tile_column=? OR tile_row=? OR tile_row=?)",
                    (z, min_col, max_col, min_row, max_row),
                ).fetchall()

                for col, row, data in boundary:
                    try:
                        with rasterio.MemoryFile(data) as mf:
                            with mf.open() as ds:
                                arr = ds.read()
                        has_data = np.any(arr[:3] > nodata_threshold, axis=0)
                        top = has_data[:edge_pixels, :].mean()
                        bot = has_data[-edge_pixels:, :].mean()
                        left = has_data[:, :edge_pixels].mean()
                        right = has_data[:, -edge_pixels:].mean()

                        if min(top, bot, left, right) < min_edge_fill:
                            conn.execute(
                                "DELETE FROM tiles WHERE zoom_level=? "
                                "AND tile_column=? AND tile_row=?",
                                (z, col, row),
                            )
                            removed_this_round += 1
                    except Exception:
                        pass

                conn.commit()
                total_removed += removed_this_round

        if total_removed:
            min_z = conn.execute("SELECT MIN(zoom_level) FROM tiles").fetchone()[0]
            max_z = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()[0]
            if min_z is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (name, value) VALUES ('minzoom', ?)",
                    (str(min_z),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO metadata (name, value) VALUES ('maxzoom', ?)",
                    (str(max_z),),
                )
            conn.commit()
            log.info("Eroded %d nodata-edge tiles from %s", total_removed, mbtiles_path)

        return total_removed
    finally:
        conn.close()
