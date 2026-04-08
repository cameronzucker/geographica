#!/usr/bin/env python3
"""Extract OSM amenities, shops, and public land from PBF and index into SQLite FTS5.

Uses osmium CLI to clip, filter, and export features from an OSM PBF file,
then parses the GeoJSONSeq output, normalizes operators, deduplicates,
and writes to osm_pois/osm_fts tables in the target SQLite database.

Usage:
  python3 build_osm_pois.py \
    --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
    --output /srv/geographica/data/poi.sqlite \
    --bbox "-124.8,31.3,-102.0,49.0"

  # For testing (skip osmium, use pre-extracted GeoJSONSeq):
  python3 build_osm_pois.py \
    --geojsonseq tests/fixtures/test_osm_features.geojsonseq \
    --output /tmp/test.sqlite \
    --bbox "-124.8,31.3,-102.0,49.0"
"""

import argparse
import json
import logging
import math
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from shapely.geometry import shape

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
EARTH_RADIUS_M = 6_371_000

TAG_FILTERS = [
    "amenity=*",
    "shop=*",
    "tourism=*",
    "leisure=*",
    "healthcare=*",
    "highway=rest_area",
    "highway=services",
    "boundary=protected_area",
    "boundary=national_park",
]

# Dedup radius: 50m for commercial, 100m for natural/boundary
COMMERCIAL_KEYS = {"amenity", "shop"}
COMMERCIAL_DEDUP_M = 50
DEFAULT_DEDUP_M = 100

OPERATOR_NORMALIZE = {
    "US Bureau of Land Management": "BLM",
    "Bureau of Land Management": "BLM",
    "BLM": "BLM",
    "BLM_FFO": "BLM",
    "United States Forest Service": "USFS",
    "US Forest Service": "USFS",
    "USFS": "USFS",
    "National Park Service": "NPS",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def parse_bbox(s: str) -> tuple[float, float, float, float]:
    """Parse 'west,south,east,north' string to tuple."""
    parts = [float(x.strip()) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be west,south,east,north")
    return tuple(parts)  # type: ignore[return-value]


def in_bbox(lat: float, lon: float,
            bbox: tuple[float, float, float, float]) -> bool:
    west, south, east, north = bbox
    return south <= lat <= north and west <= lon <= east


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two lat/lon points."""
    rlat1, rlon1, rlat2, rlon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def normalize_operator(raw: str | None) -> str | None:
    """Normalize operator names. Case-sensitive lookup."""
    if raw is None:
        return None
    return OPERATOR_NORMALIZE.get(raw, raw)


def extract_centroid(geometry: dict) -> tuple[float, float] | None:
    """Extract (lat, lon) from a GeoJSON geometry. Returns None on failure.

    - Point: use coordinates directly
    - Polygon/MultiPolygon: compute centroid via Shapely
    - LineString: use midpoint
    """
    geom_type = geometry.get("type", "")
    coords = geometry.get("coordinates")
    if not coords:
        return None

    try:
        if geom_type == "Point":
            lon, lat = coords[0], coords[1]
            return (lat, lon)
        elif geom_type in ("Polygon", "MultiPolygon"):
            centroid = shape(geometry).centroid
            return (centroid.y, centroid.x)
        elif geom_type == "LineString":
            mid_idx = len(coords) // 2
            lon, lat = coords[mid_idx][0], coords[mid_idx][1]
            return (lat, lon)
        else:
            # GeometryCollection or other -- try Shapely
            centroid = shape(geometry).centroid
            return (centroid.y, centroid.x)
    except Exception:
        return None


def resolve_display_name(props: dict) -> str | None:
    """Resolve display name from OSM properties: name || brand || operator.

    Returns None if none are present (feature should be skipped).
    """
    name = props.get("name")
    if name and name.strip():
        return name.strip()
    brand = props.get("brand")
    if brand and brand.strip():
        return brand.strip()
    operator = props.get("operator")
    if operator and operator.strip():
        return operator.strip()
    return None


def extract_osm_tag(props: dict) -> tuple[str, str] | None:
    """Extract the primary OSM key/value pair from properties.

    Checks tags in priority order matching TAG_FILTERS.
    Returns (osm_key, osm_value) or None.
    """
    # Priority order: amenity, shop, tourism, leisure, healthcare, highway, boundary
    for key in ("amenity", "shop", "tourism", "leisure", "healthcare", "highway", "boundary"):
        val = props.get(key)
        if val:
            return (key, val)
    return None


def make_dedup_key(name: str, lat: float, lon: float) -> tuple[str, float, float]:
    """Create a dedup key: (name_lower, rounded_lat, rounded_lon).

    Rounding to 3 decimal places (~111m) approximates the dedup radius.
    """
    return (name.lower(), round(lat, 3), round(lon, 3))


# ---------------------------------------------------------------------------
# Osmium pipeline
# ---------------------------------------------------------------------------
def run_osmium_pipeline(
    pbf_path: str,
    bbox: tuple[float, float, float, float],
    work_dir: str,
) -> str:
    """Run osmium extract -> tags-filter -> export pipeline.

    Returns path to the output GeoJSONSeq file.
    """
    west, south, east, north = bbox
    clipped_pbf = os.path.join(work_dir, "clipped.pbf")
    filtered_pbf = os.path.join(work_dir, "filtered.pbf")
    geojsonseq = os.path.join(work_dir, "features.geojsonseq")

    # Step 1: Clip to bbox (MUST come before tags-filter)
    log.info("osmium extract --bbox %s,%s,%s,%s ...", west, south, east, north)
    subprocess.run(
        [
            "osmium", "extract",
            "--bbox", f"{west},{south},{east},{north}",
            "--strategy", "complete_ways",
            "--output", clipped_pbf,
            "--overwrite",
            pbf_path,
        ],
        check=True,
    )
    log.info("Clipped PBF: %s (%.1f MB)", clipped_pbf,
             os.path.getsize(clipped_pbf) / 1_048_576)

    # Step 2: Filter by tags
    filter_args = []
    for tag in TAG_FILTERS:
        filter_args.append(tag)
    log.info("osmium tags-filter with %d tag filters ...", len(TAG_FILTERS))
    subprocess.run(
        [
            "osmium", "tags-filter",
            clipped_pbf,
            *filter_args,
            "--output", filtered_pbf,
            "--overwrite",
        ],
        check=True,
    )
    log.info("Filtered PBF: %s (%.1f MB)", filtered_pbf,
             os.path.getsize(filtered_pbf) / 1_048_576)

    # Step 3: Export to GeoJSONSeq
    log.info("osmium export to GeoJSONSeq ...")
    subprocess.run(
        [
            "osmium", "export",
            "-f", "geojsonseq",
            "--output", geojsonseq,
            "--overwrite",
            filtered_pbf,
        ],
        check=True,
    )
    log.info("GeoJSONSeq: %s (%.1f MB)", geojsonseq,
             os.path.getsize(geojsonseq) / 1_048_576)

    return geojsonseq


# ---------------------------------------------------------------------------
# GeoJSONSeq parsing
# ---------------------------------------------------------------------------
def parse_geojsonseq(
    path: str,
    bbox: tuple[float, float, float, float],
) -> list[dict]:
    """Parse a GeoJSONSeq file and return normalized feature dicts.

    Each dict has: name, osm_key, osm_value, operator, osm_type, osm_id, lat, lon
    Features without name/brand/operator are skipped.
    Features outside bbox are skipped.
    """
    features = []
    skipped_unnamed = 0
    skipped_bbox = 0
    skipped_no_geom = 0
    skipped_no_tag = 0

    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                feature = json.loads(line)
            except json.JSONDecodeError:
                log.warning("Skipping malformed JSON at line %d", line_num)
                continue

            props = feature.get("properties", {})
            geometry = feature.get("geometry")

            # Extract display name
            display_name = resolve_display_name(props)
            if display_name is None:
                skipped_unnamed += 1
                continue

            # Extract OSM tag
            tag = extract_osm_tag(props)
            if tag is None:
                skipped_no_tag += 1
                continue
            osm_key, osm_value = tag

            # Extract centroid
            if geometry is None:
                skipped_no_geom += 1
                continue
            centroid = extract_centroid(geometry)
            if centroid is None:
                skipped_no_geom += 1
                continue
            lat, lon = centroid

            # Bbox filter
            if not in_bbox(lat, lon, bbox):
                skipped_bbox += 1
                continue

            # Normalize operator
            raw_operator = props.get("operator")
            operator = normalize_operator(raw_operator)

            # OSM metadata from osmium export
            osm_type = props.get("@type")  # "node", "way", "relation"
            osm_id = props.get("@id")

            features.append({
                "name": display_name,
                "osm_key": osm_key,
                "osm_value": osm_value,
                "operator": operator,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "lat": lat,
                "lon": lon,
            })

    log.info(
        "Parsed %d features (skipped: %d unnamed, %d outside bbox, "
        "%d no geometry, %d no matching tag)",
        len(features), skipped_unnamed, skipped_bbox,
        skipped_no_geom, skipped_no_tag,
    )
    return features


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def deduplicate_features(features: list[dict]) -> list[dict]:
    """Remove duplicate features (same name within dedup radius).

    Uses dict keyed by (name_lower, round(lat,3), round(lon,3)) for O(n) dedup.
    Commercial POIs (amenity, shop) use 50m radius; others use 100m.
    """
    seen: dict[tuple[str, float, float], dict] = {}
    kept = []
    duplicates = 0

    for feat in features:
        key = make_dedup_key(feat["name"], feat["lat"], feat["lon"])
        dedup_radius = COMMERCIAL_DEDUP_M if feat["osm_key"] in COMMERCIAL_KEYS else DEFAULT_DEDUP_M

        if key in seen:
            existing = seen[key]
            dist = haversine_m(feat["lat"], feat["lon"],
                               existing["lat"], existing["lon"])
            if dist <= dedup_radius:
                duplicates += 1
                continue

        seen[key] = feat
        kept.append(feat)

    log.info("Dedup: %d features kept, %d duplicates removed", len(kept), duplicates)
    return kept


# ---------------------------------------------------------------------------
# Database write
# ---------------------------------------------------------------------------
def write_to_sqlite(features: list[dict], db_path: str) -> None:
    """Write features to osm_pois table + osm_fts FTS5 index.

    Idempotent: drops and recreates osm_pois and osm_fts on each run.
    Preserves other tables (poi_features, poi_fts) in the same database.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")

    # Drop and recreate (idempotent)
    conn.execute("DROP TABLE IF EXISTS osm_fts")
    conn.execute("DROP TABLE IF EXISTS osm_pois")

    conn.execute("""
        CREATE TABLE osm_pois (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            osm_key TEXT NOT NULL,
            osm_value TEXT NOT NULL,
            operator TEXT,
            osm_type TEXT,
            osm_id INTEGER,
            lat REAL NOT NULL,
            lon REAL NOT NULL
        )
    """)

    conn.execute("""
        CREATE VIRTUAL TABLE osm_fts USING fts5(
            name, osm_value, operator,
            content=osm_pois,
            content_rowid=id
        )
    """)

    # Insert features
    insert_sql = """
        INSERT INTO osm_pois (name, osm_key, osm_value, operator, osm_type, osm_id, lat, lon)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    fts_insert_sql = """
        INSERT INTO osm_fts (rowid, name, osm_value, operator)
        VALUES (?, ?, ?, ?)
    """

    for feat in features:
        cur = conn.execute(insert_sql, (
            feat["name"],
            feat["osm_key"],
            feat["osm_value"],
            feat["operator"],
            feat["osm_type"],
            feat["osm_id"],
            feat["lat"],
            feat["lon"],
        ))
        rowid = cur.lastrowid
        conn.execute(fts_insert_sql, (
            rowid,
            feat["name"],
            feat["osm_value"],
            feat["operator"] or "",
        ))

    # Create indexes
    conn.execute("CREATE INDEX idx_osm_pois_latlon ON osm_pois (lat, lon)")
    conn.execute("CREATE INDEX idx_osm_pois_category_geo ON osm_pois (osm_key, osm_value, lat, lon)")

    conn.commit()
    conn.close()

    log.info("Wrote %d features to %s (osm_pois + osm_fts)", len(features), db_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Extract OSM amenities and public land into SQLite FTS5 index"
    )
    parser.add_argument("--pbf", help="Path to OSM PBF file")
    parser.add_argument("--output", required=True, help="Path to output SQLite database")
    parser.add_argument("--bbox", default="-124.8,31.3,-102.0,49.0",
                        help="Bounding box: west,south,east,north")
    parser.add_argument("--geojsonseq",
                        help="Pre-extracted GeoJSONSeq file (skip osmium steps)")
    args = parser.parse_args()

    if not args.pbf and not args.geojsonseq:
        parser.error("Either --pbf or --geojsonseq is required")

    bbox = parse_bbox(args.bbox)

    if args.geojsonseq:
        # Direct GeoJSONSeq mode (testing / debugging)
        geojsonseq_path = args.geojsonseq
        log.info("Using pre-extracted GeoJSONSeq: %s", geojsonseq_path)
    else:
        # Full osmium pipeline
        if not shutil.which("osmium"):
            log.error("osmium CLI not found. Install with: apt install osmium-tool")
            sys.exit(1)

        if not os.path.exists(args.pbf):
            log.error("PBF file not found: %s", args.pbf)
            sys.exit(1)

        work_dir = tempfile.mkdtemp(prefix="osm_pois_")
        try:
            geojsonseq_path = run_osmium_pipeline(args.pbf, bbox, work_dir)
        except subprocess.CalledProcessError as e:
            log.error("osmium pipeline failed: %s", e)
            sys.exit(1)

    # Parse features
    features = parse_geojsonseq(geojsonseq_path, bbox)

    # Deduplicate
    features = deduplicate_features(features)

    # Write to SQLite
    write_to_sqlite(features, args.output)

    # Cleanup temp files (only if we created them)
    if not args.geojsonseq:
        import shutil as shutil_mod
        shutil_mod.rmtree(work_dir, ignore_errors=True)
        log.info("Cleaned up temp directory: %s", work_dir)

    log.info("Done. %d OSM POIs indexed.", len(features))


if __name__ == "__main__":
    main()
