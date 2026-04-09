"""Build a county lookup SQLite database from Census TIGER/Line data.

Downloads tl_2024_us_county.zip from the Census Bureau, extracts county
boundaries using GDAL/OGR, and builds a SQLite database with an rtree spatial
index for fast bounding-box intersection queries.

Usage:
    python scripts/build_county_index.py --output data/counties.sqlite
    python scripts/build_county_index.py --output data/counties.sqlite --shapefile /tmp/tl_2024_us_county.shp
"""

import argparse
import io
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# TIGER/Line 2024 county shapefile
TIGER_URL = "https://www2.census.gov/geo/tiger/TIGER2024/COUNTY/tl_2024_us_county.zip"

# FIPS code → state abbreviation (all 50 states + DC + territories)
STATE_FIPS = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
    "78": "VI",
}


def counties_for_bbox(
    db_path: str,
    west: float,
    south: float,
    east: float,
    north: float,
) -> list[tuple]:
    """Return counties whose bounding boxes intersect the given bbox.

    Uses the rtree spatial index for fast intersection queries.

    Args:
        db_path: Path to the counties SQLite database.
        west:    Western longitude of query bbox.
        south:   Southern latitude of query bbox.
        east:    Eastern longitude of query bbox.
        north:   Northern latitude of query bbox.

    Returns:
        List of (fips, name, state_abbr, area_sq_km) tuples ordered by
        state_abbr, then name.
    """
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT c.fips, c.name, c.state_abbr, c.area_sq_km
            FROM counties c
            JOIN counties_rtree r ON r.id = c.rowid
            WHERE r.min_lon <= ?
              AND r.max_lon >= ?
              AND r.min_lat <= ?
              AND r.max_lat >= ?
            ORDER BY c.state_abbr, c.name
            """,
            (east, west, north, south),
        ).fetchall()
    finally:
        conn.close()
    return [(fips, name, state_abbr, float(area)) for fips, name, state_abbr, area in rows]


def estimate_download_gb(total_area_sq_km: float) -> float:
    """Estimate NAIP download size in GB for a given total county area.

    Formula: area_sq_km * 0.4 / 1000  (empirical: ~0.4 MB per sq km at 1m res)

    Args:
        total_area_sq_km: Sum of area_sq_km for all selected counties.

    Returns:
        Estimated download size in gigabytes.
    """
    return total_area_sq_km * 0.4 / 1000.0


def build_database(output_path: str, shapefile_path: str | None = None) -> None:
    """Build the county SQLite database from a TIGER/Line shapefile.

    Downloads the shapefile from the Census Bureau if shapefile_path is not
    provided. Requires GDAL/OGR bindings (osgeo.ogr).

    Args:
        output_path:    Path to write the output SQLite database.
        shapefile_path: Optional path to an already-downloaded .shp file.
    """
    try:
        from osgeo import ogr
    except ImportError:
        print(
            "ERROR: GDAL/OGR Python bindings not found. "
            "Install with: pip install gdal  or  apt install python3-gdal",
            file=sys.stderr,
        )
        sys.exit(1)

    tmp_dir = None
    if shapefile_path is None:
        print(f"Downloading {TIGER_URL} …")
        tmp_dir = tempfile.mkdtemp()
        zip_path = Path(tmp_dir) / "county.zip"
        urllib.request.urlretrieve(TIGER_URL, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)
        # Find the .shp file
        shp_files = list(Path(tmp_dir).glob("*.shp"))
        if not shp_files:
            raise RuntimeError("No .shp file found in downloaded ZIP")
        shapefile_path = str(shp_files[0])
        print(f"Extracted shapefile: {shapefile_path}")

    print(f"Reading {shapefile_path} …")
    ds = ogr.Open(shapefile_path)
    if ds is None:
        raise RuntimeError(f"OGR could not open {shapefile_path}")
    layer = ds.GetLayer(0)

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    conn = sqlite3.connect(str(output))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE counties (
            fips TEXT PRIMARY KEY, name TEXT NOT NULL,
            state_fips TEXT NOT NULL, state_abbr TEXT NOT NULL,
            area_sq_km REAL, min_lon REAL, min_lat REAL, max_lon REAL, max_lat REAL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE counties_rtree USING rtree(
            id, min_lon, max_lon, min_lat, max_lat
        )
    """)

    count = 0
    for feature in layer:
        state_fips = feature.GetField("STATEFP")
        county_fips = feature.GetField("COUNTYFP")
        name = feature.GetField("NAME")
        area_land = feature.GetField("ALAND")  # square meters

        if state_fips is None or county_fips is None:
            continue

        fips = state_fips + county_fips
        state_abbr = STATE_FIPS.get(state_fips, state_fips)
        area_sq_km = (area_land or 0) / 1_000_000.0

        geom = feature.GetGeometryRef()
        if geom is None:
            continue
        env = geom.GetEnvelope()  # (min_lon, max_lon, min_lat, max_lat)
        min_lon, max_lon, min_lat, max_lat = env

        conn.execute(
            "INSERT OR REPLACE INTO counties VALUES (?,?,?,?,?,?,?,?,?)",
            (fips, name, state_fips, state_abbr, area_sq_km,
             min_lon, min_lat, max_lon, max_lat),
        )
        rowid = conn.execute(
            "SELECT rowid FROM counties WHERE fips = ?", (fips,)
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO counties_rtree VALUES (?,?,?,?,?)",
            (rowid, min_lon, max_lon, min_lat, max_lat),
        )
        count += 1

    conn.commit()
    conn.close()
    ds = None  # Close OGR dataset

    size_mb = output.stat().st_size / 1_048_576
    print(f"Wrote {count} counties to {output_path} ({size_mb:.1f} MB)")

    if tmp_dir:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build county lookup SQLite database from Census TIGER/Line data."
    )
    parser.add_argument(
        "--output", required=True, help="Path to output SQLite database"
    )
    parser.add_argument(
        "--shapefile",
        default=None,
        help="Path to existing .shp file (skips download if provided)",
    )
    args = parser.parse_args()
    build_database(args.output, args.shapefile)


if __name__ == "__main__":
    main()
