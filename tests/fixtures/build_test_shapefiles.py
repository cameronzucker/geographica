"""Generate synthetic NOAA tile-index shapefiles for Phase 5 integration tests.

Emits tests/fixtures/noaa_tile_indexes/{arizona,utah}_test.{shp,shx,dbf,prj}
with 10 tile footprints each + one intentional border-quad that appears in
both state shapefiles with filename "m_border.tif".

Run from the repo root:
    python tests/fixtures/build_test_shapefiles.py

Commit the generated artifacts so CI doesn't need GDAL to rebuild them.
The script uses the system `ogr2ogr` / `ogrinfo` CLI or the Python osgeo
bindings (checked in that order). If neither is available it falls back to
writing raw Shapefile bytes (minimal ESRI binary format).
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Coordinate definitions
# ---------------------------------------------------------------------------
# Arizona bounding box: (-114.82, 31.33, -109.05, 37.00)
# We place 10 non-overlapping 1°×1° tiles.  The first nine are pure-AZ;
# the tenth (index 9) is the border quad at (-110.0, 36.0, -109.0, 37.0) —
# this footprint is also near the UT/NM/CO corner so we include it in the
# Utah shapefile too with the same filename "m_border.tif".

AZ_TILES = [
    # (west, south, east, north, filename)
    (-114.0, 32.0, -113.0, 33.0, "m_az_0.tif"),
    (-113.0, 32.0, -112.0, 33.0, "m_az_1.tif"),
    (-112.0, 32.0, -111.0, 33.0, "m_az_2.tif"),
    (-114.0, 33.0, -113.0, 34.0, "m_az_3.tif"),
    (-113.0, 33.0, -112.0, 34.0, "m_az_4.tif"),
    (-112.0, 33.0, -111.0, 34.0, "m_az_5.tif"),
    (-114.0, 34.0, -113.0, 35.0, "m_az_6.tif"),
    (-113.0, 34.0, -112.0, 35.0, "m_az_7.tif"),
    (-112.0, 34.0, -111.0, 35.0, "m_az_8.tif"),
    # border quad — same record will appear in UT shapefile
    (-110.0, 36.0, -109.0, 37.0, "m_border.tif"),
]

# Utah bounding box: (-114.05, 37.00, -109.04, 42.00)
UT_TILES = [
    (-114.0, 37.0, -113.0, 38.0, "m_ut_0.tif"),
    (-113.0, 37.0, -112.0, 38.0, "m_ut_1.tif"),
    (-112.0, 37.0, -111.0, 38.0, "m_ut_2.tif"),
    (-114.0, 38.0, -113.0, 39.0, "m_ut_3.tif"),
    (-113.0, 38.0, -112.0, 39.0, "m_ut_4.tif"),
    (-112.0, 38.0, -111.0, 39.0, "m_ut_5.tif"),
    (-114.0, 39.0, -113.0, 40.0, "m_ut_6.tif"),
    (-113.0, 39.0, -112.0, 40.0, "m_ut_7.tif"),
    (-112.0, 39.0, -111.0, 40.0, "m_ut_8.tif"),
    # border quad — same filename as the AZ border tile
    (-110.0, 36.0, -109.0, 37.0, "m_border.tif"),
]

WGS84_PRJ = (
    'GEOGCS["WGS 84",'
    'DATUM["WGS_1984",'
    'SPHEROID["WGS 84",6378137,298.257223563]],'
    'PRIMEM["Greenwich",0],'
    'UNIT["degree",0.0174532925199433,'
    'AUTHORITY["EPSG","9122"]],'
    'AUTHORITY["EPSG","4326"]]'
)

OUT_DIR = Path(__file__).parent / "noaa_tile_indexes"


# ---------------------------------------------------------------------------
# Backend: osgeo.ogr (preferred)
# ---------------------------------------------------------------------------

def _write_with_osgeo(tiles: list[tuple], out_stem: Path) -> None:
    from osgeo import ogr, osr  # type: ignore[import]

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)

    driver = ogr.GetDriverByName("ESRI Shapefile")
    if out_stem.with_suffix(".shp").exists():
        driver.DeleteDataSource(str(out_stem.with_suffix(".shp")))

    ds = driver.CreateDataSource(str(out_stem.with_suffix(".shp")))
    layer = ds.CreateLayer("tileindex", srs, ogr.wkbPolygon)

    field_defn = ogr.FieldDefn("filename", ogr.OFTString)
    field_defn.SetWidth(64)
    layer.CreateField(field_defn)

    for west, south, east, north, fname in tiles:
        ring = ogr.Geometry(ogr.wkbLinearRing)
        ring.AddPoint(west, south)
        ring.AddPoint(east, south)
        ring.AddPoint(east, north)
        ring.AddPoint(west, north)
        ring.AddPoint(west, south)
        poly = ogr.Geometry(ogr.wkbPolygon)
        poly.AddGeometry(ring)

        feat = ogr.Feature(layer.GetLayerDefn())
        feat.SetGeometry(poly)
        feat.SetField("filename", fname)
        layer.CreateFeature(feat)
        feat = None

    ds = None  # flush


# ---------------------------------------------------------------------------
# Backend: ogr2ogr CLI via GeoJSON intermediary
# ---------------------------------------------------------------------------

def _write_with_ogr2ogr_cli(tiles: list[tuple], out_stem: Path) -> None:
    """Build shapefile via GeoJSON + ogr2ogr (requires GDAL CLI on PATH)."""
    features = []
    for west, south, east, north, fname in tiles:
        features.append({
            "type": "Feature",
            "properties": {"filename": fname},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]],
            },
        })
    geojson = {"type": "FeatureCollection", "features": features}

    shp_path = out_stem.with_suffix(".shp")
    # Delete existing shapefile components if present
    for ext in (".shp", ".shx", ".dbf", ".prj"):
        p = out_stem.with_suffix(ext)
        if p.exists():
            p.unlink()

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".geojson", delete=False
    ) as tmp:
        json.dump(geojson, tmp)
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "ogr2ogr",
                "-f", "ESRI Shapefile",
                "-t_srs", "EPSG:4326",
                str(shp_path),
                tmp_path,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ogr2ogr failed: {result.stderr}")
        # ogr2ogr may not write a .prj for some GeoJSON inputs — ensure it
        prj_path = out_stem.with_suffix(".prj")
        if not prj_path.exists():
            prj_path.write_text(WGS84_PRJ)
    finally:
        os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Backend: pyshp (shapefile module)
# ---------------------------------------------------------------------------

def _write_with_pyshp(tiles: list[tuple], out_stem: Path) -> None:
    import shapefile  # type: ignore[import]  # pyshp

    with shapefile.Writer(str(out_stem), shapeType=shapefile.POLYGON) as w:
        w.field("filename", "C", size=64)
        for west, south, east, north, fname in tiles:
            w.poly([
                [
                    [west, south],
                    [east, south],
                    [east, north],
                    [west, north],
                    [west, south],
                ]
            ])
            w.record(fname)

    out_stem.with_suffix(".prj").write_text(WGS84_PRJ)


# ---------------------------------------------------------------------------
# Raw binary Shapefile writer (last resort — no deps)
# ---------------------------------------------------------------------------

def _write_shx_shp_raw(tiles: list[tuple], out_stem: Path) -> None:
    """Minimal ESRI Shapefile (type 5 = Polygon) with one-ring rectangles.

    References:
      ESRI Shapefile Technical Description, July 1998, §3 (file format)
    """
    # Pre-compute record data
    records: list[bytes] = []
    for west, south, east, north, _fname in tiles:
        coords = [
            (west, south),
            (east, south),
            (east, north),
            (west, north),
            (west, south),  # close ring
        ]
        # Content:
        #   shape_type (4 bytes LE)  = 5
        #   bbox (4×8 bytes LE)
        #   num_parts (4 bytes LE) = 1
        #   num_points (4 bytes LE) = 5
        #   parts[0] (4 bytes LE) = 0
        #   points (5×16 bytes LE)
        body = struct.pack("<i", 5)  # shape type Polygon
        body += struct.pack("<4d", west, south, east, north)  # bbox
        body += struct.pack("<ii", 1, 5)  # num_parts, num_points
        body += struct.pack("<i", 0)  # parts[0] = 0
        for x, y in coords:
            body += struct.pack("<2d", x, y)
        records.append(body)

    # File-level bbox
    all_west = min(t[0] for t in tiles)
    all_south = min(t[1] for t in tiles)
    all_east = max(t[2] for t in tiles)
    all_north = max(t[3] for t in tiles)

    def _shp_header(file_length_16: int) -> bytes:
        h = struct.pack(">iiiiii", 9994, 0, 0, 0, 0, 0)  # file code + unused
        h += struct.pack(">i", file_length_16)  # file length in 16-bit words
        h += struct.pack("<ii", 1000, 5)  # version, shape type Polygon
        h += struct.pack("<8d",
                         all_west, all_south, all_east, all_north,
                         0.0, 0.0, 0.0, 0.0)  # bbox + Z/M ranges
        return h

    # Build .shp and .shx
    shp_content = b""
    shx_content = b""
    offset = 50  # header is 50 16-bit words = 100 bytes

    for i, rec in enumerate(records):
        content_len = len(rec) // 2  # in 16-bit words
        # SHP: record header (big-endian record number + content length)
        shp_content += struct.pack(">ii", i + 1, content_len)
        shp_content += rec
        # SHX: offset + content length (both big-endian, in 16-bit words)
        shx_content += struct.pack(">ii", offset, content_len)
        offset += 4 + content_len  # 4 words for record header

    shp_file_len = 50 + len(shp_content) // 2
    shx_file_len = 50 + len(shx_content) // 2

    shp_header = _shp_header(shp_file_len)
    # For .shx the header is identical except file_length
    shx_header = _shp_header(shx_file_len)

    out_stem.with_suffix(".shp").write_bytes(shp_header + shp_content)
    out_stem.with_suffix(".shx").write_bytes(shx_header + shx_content)

    # .dbf — dBASE III format with one "filename" text field
    _write_dbf([(fname,) for _, _, _, _, fname in tiles], out_stem)
    out_stem.with_suffix(".prj").write_text(WGS84_PRJ)


def _write_dbf(rows: list[tuple[str]], out_stem: Path) -> None:
    """Minimal dBASE III .dbf with a single CHARACTER field 'filename' (64 chars)."""
    field_name = b"filename\x00\x00\x00"  # 11 bytes
    field_type = b"C"
    field_len = 64
    # Header: 32 bytes base + 32 bytes per field + 1 terminator byte
    num_records = len(rows)
    header_size = 32 + 32 + 1  # 65 bytes
    record_size = 1 + field_len  # deletion flag + field data

    import datetime
    now = datetime.date.today()
    header = struct.pack(
        "<BBBB",
        3,            # version = dBASE III
        now.year - 1900,
        now.month,
        now.day,
    )
    header += struct.pack("<I", num_records)
    header += struct.pack("<HH", header_size, record_size)
    header += b"\x00" * 20  # reserved

    # Field descriptor
    fd = field_name + field_type + b"\x00" * 4  # name + type + reserved
    fd += struct.pack("<B", field_len)  # field length
    fd += b"\x00" * 15  # decimals + reserved
    header += fd
    header += b"\r"  # header terminator

    assert len(header) == header_size, f"{len(header)} != {header_size}"

    records = b""
    for (fname,) in rows:
        records += b" "  # not deleted
        fname_bytes = fname.encode("ascii", "replace")[:field_len]
        records += fname_bytes.ljust(field_len)

    out_stem.with_suffix(".dbf").write_bytes(header + records + b"\x1a")  # EOF


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_shapefiles(out_dir: Path = OUT_DIR) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    backends = []
    try:
        from osgeo import ogr  # noqa: F401
        backends.append(("osgeo", _write_with_osgeo))
    except ImportError:
        pass

    if not backends:
        # Try ogr2ogr CLI
        try:
            result = subprocess.run(
                ["ogr2ogr", "--version"], capture_output=True, timeout=5
            )
            if result.returncode == 0:
                backends.append(("ogr2ogr-cli", _write_with_ogr2ogr_cli))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if not backends:
        try:
            import shapefile  # noqa: F401
            backends.append(("pyshp", _write_with_pyshp))
        except ImportError:
            pass

    if not backends:
        print(
            "No GDAL (osgeo), ogr2ogr CLI, or pyshp found — using raw binary writer.",
            file=sys.stderr,
        )
        backends.append(("raw", _write_shx_shp_raw))

    write_fn = backends[0][1]
    backend_name = backends[0][0]
    print(f"Using backend: {backend_name}", file=sys.stderr)

    datasets = [
        ("arizona_test", AZ_TILES),
        ("utah_test", UT_TILES),
    ]
    for stem, tiles in datasets:
        out_stem = out_dir / stem
        write_fn(tiles, out_stem)
        shp = out_stem.with_suffix(".shp")
        assert shp.exists(), f"expected {shp} to be created"
        print(f"  wrote {shp}", file=sys.stderr)

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    build_shapefiles()
