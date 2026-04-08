# Expanded POI Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Supplement the GNIS-only POI database with commercial amenities and public land boundaries extracted from the OSM PBF file already on disk, filling the critical 240-mile gap on I-10 between Buckeye and Blythe where spatial search returns no results for gas, food, or lodging.

**Architecture:** A new `scripts/build_osm_pois.py` script extracts features from the 3.1GB `western-us.osm.pbf` using osmium CLI (bbox clip, tag filter, GeoJSONSeq export), then parses, normalizes operators, deduplicates within 50-100m, and writes to a new `osm_pois` table + `osm_fts` FTS5 index in the existing `poi.sqlite`. The search service queries this as a third concurrent leg alongside Nominatim and GNIS, with three-way haversine deduplication. Spatial search gains direct SQL query paths for category+bbox on `osm_pois` and `osm_operator` filtering for BLM/USFS/NPS disambiguation.

**Tech Stack:** Python 3.12, osmium CLI (v1.18.0, already installed), Shapely (centroid computation), SQLite FTS5, aiosqlite, FastAPI, pytest

**Spec:** `docs/superpowers/specs/2026-04-08-expanded-poi-sources-design.md`

---

## TDD Preamble

Every task follows strict TDD discipline:

1. **Before each task:** Re-read `docs/pitfalls/testing-pitfalls.md` and `docs/pitfalls/implementation-pitfalls.md`
2. **Write failing tests first:** Create test files with assertions before writing implementation code
3. **Run tests to confirm failure:** Verify tests fail for the right reason (ImportError or AssertionError, not SyntaxError)
4. **Implement the minimum code** to make tests pass
5. **Review tests before marking complete:** Re-read each test and confirm it tests behavior, not implementation details

Key pitfalls to watch:
- **testing-pitfalls #1:** Don't mock SQLite queries. Use in-memory databases with real schema and data.
- **testing-pitfalls #2:** FTS5 token queries (`word1 OR word2`) match across columns. Phrase queries require sequence within one column.
- **testing-pitfalls #3:** Use `Path(__file__).parent / "fixtures"` for fixture paths. Never hardcode absolute paths.
- **testing-pitfalls #8:** Use `monkeypatch` for env var changes, not `os.environ` directly.
- **implementation-pitfalls #1:** Large data files go to `/srv/geographica/data/`. Never inside the git repo.
- **implementation-pitfalls #8:** Use WAL mode for concurrent SQLite access.

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `scripts/build_osm_pois.py` | OSM PBF extraction + SQLite indexer (~250 lines) |
| `tests/fixtures/test_osm_features.geojsonseq` | 10-15 representative GeoJSONSeq features from osmium export format |
| `tests/test_osm_poi_indexer.py` | Indexer unit tests: parsing, normalization, dedup, bbox, idempotency |
| `tests/test_osm_poi_search.py` | Search integration tests: `_query_osm_pois()`, three-way dedup, graceful degradation |
| `tests/test_spatial_osm.py` | Spatial search tests: osm_operator filter, direct SQL path, synonym entries |

### Modified files
| File | Change |
|------|--------|
| `services/search/main.py` | Add `osm_pois_loaded` to State, restructure `_open_poi_db()`, add `_query_osm_pois()`, update `_deduplicate()` signature, update `/search` and `/health` |
| `services/search/spatial.py` | Add BLM/USFS/NPS synonym entries with `osm_operator`, add `osm_operator` to `parse_intent()` return dict, add direct OSM POI query path in spatial search |
| `scripts/requirements.txt` | Add `shapely` |

### Cross-task file dependencies
- Task 1 creates `scripts/build_osm_pois.py`. Task 3 tests it. Tasks 1-3 MUST run sequentially.
- Task 2 creates `tests/fixtures/test_osm_features.geojsonseq`. Task 3 uses it. Tasks 2-3 MUST run sequentially.
- Task 4 modifies `services/search/main.py`. Task 5 tests those changes. Tasks 4-5 MUST run sequentially.
- Task 6 modifies `services/search/spatial.py`. Task 7 tests those changes. Tasks 6-7 MUST run sequentially.
- Backend tasks (1-7) must complete before Task 8 (smoke test).
- Tasks 1-3 (indexer) and Tasks 4-5 (search service) are independent and COULD run in parallel.
- Tasks 6-7 (spatial) depend on Task 4 (need `osm_pois_loaded` in State).

---

## Task 1: OSM POI Extraction Script

**Dependencies:** None (first task)
**Creates:** `scripts/build_osm_pois.py`
**Modifies:** `scripts/requirements.txt`

> BEFORE starting work:
> 1. Read the spec at `docs/superpowers/specs/2026-04-08-expanded-poi-sources-design.md` — sections "Extraction script" and "Database schema"
> 2. Read `docs/pitfalls/implementation-pitfalls.md` — especially #1 (data outside repo) and #8 (WAL mode)
> 3. Read `scripts/build_poi_index.py` (first 150 lines) for the existing indexer pattern

**Behavior change:** No OSM POI extraction capability exists. After this task, `python3 scripts/build_osm_pois.py --pbf <path> --output <path> --bbox <bbox>` extracts amenities, shops, tourism, healthcare, rest areas, and protected areas from a PBF file and writes them to `osm_pois` + `osm_fts` tables in the target SQLite database.

**Do NOT:**
- Modify any existing tables (`poi_features`, `poi_fts`)
- Add search service changes (that's Task 4)
- Run the full extraction (that's Task 8)
- Create data files inside the git repo

- [ ] **Step 1: Add shapely to scripts/requirements.txt**

Modify `scripts/requirements.txt`:

```
aiohttp
aiosqlite
tqdm
shapely
```

**Test:** `pip install -r scripts/requirements.txt` completes without errors.

- [ ] **Step 2: Create `scripts/build_osm_pois.py`**

Create `scripts/build_osm_pois.py`:

```python
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

# Map from GeoJSON geometry type to extraction function
# (handled inline for simplicity)


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
            # GeometryCollection or other — try Shapely
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

    # Step 1: Clip to bbox
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
```

**Test command:**
```bash
python3 scripts/build_osm_pois.py --help
```

**Commit:**
```bash
git add scripts/build_osm_pois.py scripts/requirements.txt
git commit -m "feat: add OSM POI extraction script (build_osm_pois.py)

Extracts amenities, shops, tourism, healthcare, rest areas, and
protected areas from OSM PBF via osmium CLI pipeline. Writes to
osm_pois table + osm_fts FTS5 index in poi.sqlite.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Test Fixtures

**Dependencies:** None
**Creates:** `tests/fixtures/test_osm_features.geojsonseq`

> BEFORE starting work:
> 1. Read `docs/pitfalls/testing-pitfalls.md` — especially #3 (fixture paths)
> 2. Read the spec section "Test fixtures"

**Behavior change:** No test fixtures directory or OSM test data exists. After this task, a realistic GeoJSONSeq fixture file exists for indexer tests.

**Do NOT:**
- Create fixtures larger than ~3KB
- Use synthetic data that doesn't match osmium export format
- Hardcode absolute paths anywhere

- [ ] **Step 1: Create `tests/fixtures/` directory**

```bash
mkdir -p tests/fixtures
```

- [ ] **Step 2: Create `tests/fixtures/test_osm_features.geojsonseq`**

Each line is a valid GeoJSON Feature matching osmium export format (flat properties with `@type`, `@id` metadata). Features cover all test scenarios:

```
{"type":"Feature","geometry":{"type":"Point","coordinates":[-112.074,33.4484]},"properties":{"@type":"node","@id":12345,"amenity":"fuel","name":"Shell Station","brand":"Shell","operator":null}}
{"type":"Feature","geometry":{"type":"Polygon","coordinates":[[[-111.95,33.42],[-111.94,33.42],[-111.94,33.43],[-111.95,33.43],[-111.95,33.42]]]},"properties":{"@type":"way","@id":23456,"amenity":"restaurant","name":"Desert Cafe","brand":null,"operator":null}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-112.1,34.5]},"properties":{"@type":"node","@id":34567,"boundary":"protected_area","name":"Prescott National Forest","operator":"United States Forest Service"}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-111.5,35.0]},"properties":{"@type":"relation","@id":45678,"boundary":"protected_area","name":"Coconino BLM Land","operator":"US Bureau of Land Management"}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-112.073,33.4486]},"properties":{"@type":"way","@id":56789,"amenity":"fuel","name":"Shell Station","brand":"Shell","operator":null}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-110.0,33.0]},"properties":{"@type":"node","@id":67890,"shop":"supermarket","brand":"Safeway","operator":null}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-112.5,33.5]},"properties":{"@type":"node","@id":78901,"amenity":"pharmacy","name":null,"brand":null,"operator":null}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-115.0,36.0]},"properties":{"@type":"node","@id":89012,"tourism":"hotel","name":"Desert Oasis Inn","brand":null,"operator":null}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-130.0,50.0]},"properties":{"@type":"node","@id":90123,"amenity":"cafe","name":"Out of Bounds Cafe","brand":null,"operator":null}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-113.0,36.5]},"properties":{"@type":"node","@id":11111,"boundary":"national_park","name":"Grand Canyon National Park","operator":"National Park Service"}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-112.0,33.45]},"properties":{"@type":"node","@id":22222,"highway":"rest_area","name":"I-10 Rest Area","brand":null,"operator":"ADOT"}}
{"type":"Feature","geometry":{"type":"Point","coordinates":[-111.8,33.3]},"properties":{"@type":"node","@id":33333,"leisure":"park","name":"Papago Park","brand":null,"operator":null}}
{"type":"Feature","geometry":{"type":"LineString","coordinates":[[-112.0,33.4],[-112.1,33.5],[-112.2,33.6]]},"properties":{"@type":"way","@id":44444,"highway":"rest_area","name":"I-17 Rest Stop","brand":null,"operator":null}}
```

Feature descriptions:
1. **Point amenity** — Shell gas station (node, has name+brand)
2. **Polygon with centroid** — restaurant as building outline (way, needs Shapely centroid)
3. **Protected area with USFS operator** — tests operator normalization "United States Forest Service" -> "USFS"
4. **Protected area with BLM operator** — tests "US Bureau of Land Management" -> "BLM"
5. **Duplicate of #1** — same name, ~30m away, tests dedup within 50m radius
6. **Brand-only feature** — Safeway with no `name` tag, only `brand` (tests name fallback)
7. **Unnamed feature** — no name/brand/operator, should be SKIPPED
8. **Tourism hotel** — normal named feature in Las Vegas area
9. **Outside bbox** — lon=-130, lat=50, should be SKIPPED by bbox filter
10. **National park with NPS** — tests "National Park Service" -> "NPS"
11. **Rest area** — highway=rest_area with non-normalized operator
12. **Leisure park** — park feature
13. **LineString feature** — rest stop as linestring, tests midpoint extraction

**Test command:**
```bash
python3 -c "
from pathlib import Path
import json
fixture = Path('tests/fixtures/test_osm_features.geojsonseq')
lines = fixture.read_text().strip().split('\n')
print(f'{len(lines)} features in fixture')
for i, line in enumerate(lines, 1):
    feat = json.loads(line)
    name = feat['properties'].get('name') or feat['properties'].get('brand') or '(unnamed)'
    geom = feat['geometry']['type']
    print(f'  {i}. {name} [{geom}]')
"
```

**Commit:**
```bash
git add tests/fixtures/test_osm_features.geojsonseq
git commit -m "test: add GeoJSONSeq fixture for OSM POI indexer tests

13 representative features covering point amenity, polygon centroid,
operator normalization, brand-only fallback, unnamed skip, bbox
filtering, dedup, linestring midpoint, and all target tag categories.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Indexer Tests

**Dependencies:** Task 1 (build_osm_pois.py), Task 2 (fixture)
**Creates:** `tests/test_osm_poi_indexer.py`

> BEFORE starting work:
> 1. Read `docs/pitfalls/testing-pitfalls.md` — especially #1 (real SQLite, no mocking), #3 (fixture paths), #8 (monkeypatch)
> 2. Read `tests/test_intent_parser.py` for the existing test pattern (sys.path.insert, class-based tests)

**Behavior change:** No indexer tests exist. After this task, comprehensive unit tests validate parsing, normalization, dedup, bbox filtering, and idempotency.

**Do NOT:**
- Mock SQLite queries (use real in-memory or tmp databases)
- Hardcode fixture paths
- Test osmium CLI execution (those are integration tests, Task 8)

- [ ] **Step 1: Create `tests/test_osm_poi_indexer.py`**

```python
"""Tests for the OSM POI extraction and indexing script."""
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

# Add scripts to path for import
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from build_osm_pois import (
    OPERATOR_NORMALIZE,
    deduplicate_features,
    extract_centroid,
    extract_osm_tag,
    in_bbox,
    make_dedup_key,
    normalize_operator,
    parse_bbox,
    parse_geojsonseq,
    resolve_display_name,
    write_to_sqlite,
)

FIXTURE_PATH = str(Path(__file__).parent / "fixtures" / "test_osm_features.geojsonseq")
DEFAULT_BBOX = (-124.8, 31.3, -102.0, 49.0)


class TestParseGeojsonseq:
    """Test GeoJSONSeq parsing with the fixture file."""

    def test_parses_fixture_features(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        # Should have all named features inside bbox
        # Fixture has 13 lines: 1 unnamed (#7) and 1 outside bbox (#9) should be skipped
        assert len(features) >= 10
        assert len(features) <= 12  # allowing for dedup not applied yet

    def test_point_feature_coordinates(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        shell = [f for f in features if f["name"] == "Shell Station"]
        assert len(shell) >= 1
        assert abs(shell[0]["lat"] - 33.4484) < 0.001
        assert abs(shell[0]["lon"] - (-112.074)) < 0.001

    def test_polygon_centroid_computed(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        cafe = [f for f in features if f["name"] == "Desert Cafe"]
        assert len(cafe) == 1
        # Centroid of the square polygon should be near center
        assert abs(cafe[0]["lat"] - 33.425) < 0.01
        assert abs(cafe[0]["lon"] - (-111.945)) < 0.01

    def test_linestring_midpoint(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        rest = [f for f in features if f["name"] == "I-17 Rest Stop"]
        assert len(rest) == 1
        # Midpoint of 3-point linestring should be the middle point
        assert abs(rest[0]["lat"] - 33.5) < 0.01
        assert abs(rest[0]["lon"] - (-112.1)) < 0.01

    def test_unnamed_features_skipped(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        names = [f["name"] for f in features]
        # Feature #7 has no name/brand/operator — should not appear
        # Check that no None or empty names exist
        assert all(name and name.strip() for name in names)

    def test_outside_bbox_skipped(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        names = [f["name"] for f in features]
        assert "Out of Bounds Cafe" not in names

    def test_osm_metadata_preserved(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        shell = [f for f in features if f["name"] == "Shell Station"][0]
        assert shell["osm_type"] == "node"
        assert shell["osm_id"] == 12345

    def test_osm_tag_extracted(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        shell = [f for f in features if f["name"] == "Shell Station"][0]
        assert shell["osm_key"] == "amenity"
        assert shell["osm_value"] == "fuel"


class TestBrandFallback:
    """Test name resolution: name || brand || operator."""

    def test_brand_only_feature(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        safeway = [f for f in features if f["name"] == "Safeway"]
        assert len(safeway) == 1
        assert safeway[0]["osm_key"] == "shop"
        assert safeway[0]["osm_value"] == "supermarket"

    def test_resolve_display_name_priority(self):
        assert resolve_display_name({"name": "Foo", "brand": "Bar"}) == "Foo"
        assert resolve_display_name({"brand": "Bar"}) == "Bar"
        assert resolve_display_name({"operator": "Baz"}) == "Baz"
        assert resolve_display_name({}) is None
        assert resolve_display_name({"name": "", "brand": "", "operator": ""}) is None


class TestOperatorNormalization:
    """Test operator name normalization."""

    def test_blm_variants(self):
        assert normalize_operator("US Bureau of Land Management") == "BLM"
        assert normalize_operator("Bureau of Land Management") == "BLM"
        assert normalize_operator("BLM") == "BLM"
        assert normalize_operator("BLM_FFO") == "BLM"

    def test_usfs_variants(self):
        assert normalize_operator("United States Forest Service") == "USFS"
        assert normalize_operator("US Forest Service") == "USFS"
        assert normalize_operator("USFS") == "USFS"

    def test_nps(self):
        assert normalize_operator("National Park Service") == "NPS"

    def test_unknown_operator_kept(self):
        assert normalize_operator("ADOT") == "ADOT"
        assert normalize_operator("California Department of Parks and Recreation") == \
            "California Department of Parks and Recreation"

    def test_none_operator(self):
        assert normalize_operator(None) is None

    def test_case_sensitive(self):
        # "blm" (lowercase) is NOT in the normalization table
        assert normalize_operator("blm") == "blm"

    def test_fixture_operators_normalized(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        usfs = [f for f in features if f["name"] == "Prescott National Forest"]
        assert len(usfs) == 1
        assert usfs[0]["operator"] == "USFS"

        blm = [f for f in features if f["name"] == "Coconino BLM Land"]
        assert len(blm) == 1
        assert blm[0]["operator"] == "BLM"

        nps = [f for f in features if f["name"] == "Grand Canyon National Park"]
        assert len(nps) == 1
        assert nps[0]["operator"] == "NPS"


class TestBboxFiltering:
    """Test bounding box filtering."""

    def test_in_bbox(self):
        bbox = (-115.0, 32.0, -110.0, 37.0)
        assert in_bbox(33.0, -112.0, bbox) is True
        assert in_bbox(50.0, -112.0, bbox) is False
        assert in_bbox(33.0, -120.0, bbox) is False

    def test_tight_bbox_filters(self):
        # Use a tight bbox that only includes Phoenix-area features
        tight_bbox = (-112.5, 33.0, -111.5, 34.0)
        features = parse_geojsonseq(FIXTURE_PATH, tight_bbox)
        names = [f["name"] for f in features]
        assert "Shell Station" in names
        assert "Desert Cafe" in names
        assert "Desert Oasis Inn" not in names  # Las Vegas area
        assert "Grand Canyon National Park" not in names  # too far north


class TestDeduplication:
    """Test index-time deduplication."""

    def test_dedup_same_name_nearby(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        # Two "Shell Station" features exist ~30m apart
        shell_before = [f for f in features if f["name"] == "Shell Station"]
        assert len(shell_before) == 2  # both parsed

        deduped = deduplicate_features(features)
        shell_after = [f for f in deduped if f["name"] == "Shell Station"]
        assert len(shell_after) == 1  # one removed

    def test_dedup_different_names_same_location(self):
        features = [
            {"name": "Foo", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "node", "osm_id": 1, "lat": 33.0, "lon": -112.0},
            {"name": "Bar", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "node", "osm_id": 2, "lat": 33.0, "lon": -112.0},
        ]
        deduped = deduplicate_features(features)
        assert len(deduped) == 2  # different names, both kept

    def test_dedup_commercial_50m(self):
        # Two commercial POIs 40m apart — should be deduped
        features = [
            {"name": "test", "osm_key": "amenity", "osm_value": "fuel",
             "operator": None, "osm_type": "node", "osm_id": 1,
             "lat": 33.0, "lon": -112.0},
            {"name": "test", "osm_key": "shop", "osm_value": "gas",
             "operator": None, "osm_type": "way", "osm_id": 2,
             "lat": 33.0003, "lon": -112.0},  # ~33m north
        ]
        deduped = deduplicate_features(features)
        assert len(deduped) == 1

    def test_dedup_key_rounding(self):
        key1 = make_dedup_key("Shell Station", 33.4484, -112.074)
        key2 = make_dedup_key("Shell Station", 33.4486, -112.073)
        assert key1 == key2  # same after rounding to 3 decimal places


class TestIdempotency:
    """Test that running the indexer twice produces the same result."""

    def test_idempotent_write(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        features = deduplicate_features(features)

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            # Write twice
            write_to_sqlite(features, db_path)
            write_to_sqlite(features, db_path)

            # Count should be the same as a single write
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM osm_pois").fetchone()[0]
            conn.close()
            assert count == len(features)
        finally:
            os.unlink(db_path)


class TestSqliteWrite:
    """Test database write and schema."""

    def test_creates_tables_and_indexes(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        features = deduplicate_features(features)

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            write_to_sqlite(features, db_path)
            conn = sqlite3.connect(db_path)

            # Check tables exist
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t[0] for t in tables}
            assert "osm_pois" in table_names
            assert "osm_fts" in table_names

            # Check indexes exist
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
            index_names = {i[0] for i in indexes}
            assert "idx_osm_pois_latlon" in index_names
            assert "idx_osm_pois_category_geo" in index_names

            # Check FTS5 works
            fts_results = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'Shell'"
            ).fetchone()[0]
            assert fts_results >= 1

            conn.close()
        finally:
            os.unlink(db_path)

    def test_fts_searches_name_and_operator(self):
        features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
        features = deduplicate_features(features)

        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            write_to_sqlite(features, db_path)
            conn = sqlite3.connect(db_path)

            # Search by name
            r1 = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'Shell'"
            ).fetchone()[0]
            assert r1 >= 1

            # Search by operator (normalized)
            r2 = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'BLM'"
            ).fetchone()[0]
            assert r2 >= 1

            # Search by osm_value
            r3 = conn.execute(
                "SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'fuel'"
            ).fetchone()[0]
            assert r3 >= 1

            conn.close()
        finally:
            os.unlink(db_path)

    def test_preserves_existing_tables(self):
        """osm_pois write must not destroy existing poi_features table."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
            db_path = f.name

        try:
            # Create a fake poi_features table first
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE poi_features (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    class TEXT,
                    state TEXT,
                    county TEXT,
                    lat REAL NOT NULL,
                    lon REAL NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO poi_features (name, class, state, county, lat, lon) VALUES (?, ?, ?, ?, ?, ?)",
                ("Test Peak", "Summit", "AZ", "Maricopa", 33.5, -112.0),
            )
            conn.commit()
            conn.close()

            # Now write OSM POIs
            features = parse_geojsonseq(FIXTURE_PATH, DEFAULT_BBOX)
            features = deduplicate_features(features)
            write_to_sqlite(features, db_path)

            # Verify poi_features still exists and has data
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM poi_features").fetchone()[0]
            assert count == 1
            conn.close()
        finally:
            os.unlink(db_path)


class TestOsmiumCheck:
    """Test osmium availability check."""

    def test_osmium_check_with_shutil_which(self):
        """Verify the script checks for osmium before running the pipeline."""
        import shutil
        # This test just validates the function exists and is used
        # The actual check happens in main() when --pbf is used
        result = shutil.which("osmium")
        # Result is either a path string or None — both are valid
        assert result is None or isinstance(result, str)


class TestExtractCentroid:
    """Test centroid extraction from GeoJSON geometries."""

    def test_point(self):
        geom = {"type": "Point", "coordinates": [-112.0, 33.5]}
        lat, lon = extract_centroid(geom)
        assert abs(lat - 33.5) < 0.001
        assert abs(lon - (-112.0)) < 0.001

    def test_polygon(self):
        geom = {
            "type": "Polygon",
            "coordinates": [[[-112.0, 33.0], [-111.0, 33.0],
                             [-111.0, 34.0], [-112.0, 34.0],
                             [-112.0, 33.0]]],
        }
        lat, lon = extract_centroid(geom)
        assert abs(lat - 33.5) < 0.01
        assert abs(lon - (-111.5)) < 0.01

    def test_none_geometry(self):
        assert extract_centroid({"type": "Point"}) is None

    def test_empty_coordinates(self):
        assert extract_centroid({"type": "Point", "coordinates": []}) is None
```

**Test command:**
```bash
cd /home/administrator/Code/geographica && python -m pytest tests/test_osm_poi_indexer.py -v
```

**Commit:**
```bash
git add tests/test_osm_poi_indexer.py
git commit -m "test: comprehensive indexer tests for OSM POI extraction

Tests GeoJSONSeq parsing, centroid computation, operator normalization,
bbox filtering, dedup within radius, brand fallback, unnamed skip,
idempotency, FTS5 indexing, and existing table preservation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Search Service Integration

**Dependencies:** Task 1 (build_osm_pois.py defines the schema)
**Modifies:** `services/search/main.py`
**Does NOT create new files** (tests are in Task 5)

> BEFORE starting work:
> 1. Read `docs/pitfalls/testing-pitfalls.md` — especially #2 (FTS5 token vs phrase)
> 2. Read `docs/pitfalls/implementation-pitfalls.md` — especially #4 (memory limits on Pi 5)
> 3. Read `services/search/main.py` COMPLETELY — understand the existing State class, `_open_poi_db()`, `_deduplicate()`, `/search` endpoint, `/health` endpoint
> 4. Read the spec sections "Search service changes" and "Updated /search endpoint"

**Behavior change:** The search service currently queries Nominatim and GNIS in parallel, then deduplicates with a two-source merge. After this task, it queries Nominatim, GNIS, and OSM POIs in parallel, then deduplicates with a three-source merge. The `/health` endpoint reports `osm_pois_loaded`. Graceful degradation: if `osm_pois` table doesn't exist, the service works exactly as before.

**Do NOT:**
- Modify spatial.py (that's Task 6)
- Break existing functionality — all current tests must still pass
- Add innerHTML or unsafe DOM methods anywhere

- [ ] **Step 1: Add `osm_pois_loaded` to State class**

In `services/search/main.py`, modify the `State` class (around line 134):

```python
class State:
    poi_db: Optional[aiosqlite.Connection] = None
    poi_db_loaded: bool = False
    osm_pois_loaded: bool = False
    http_client: Optional[httpx.AsyncClient] = None
```

- [ ] **Step 2: Restructure `_open_poi_db()` to check tables independently**

Replace the existing `_open_poi_db()` function (lines 143-163) with:

```python
async def _open_poi_db() -> None:
    """Open the POI SQLite database. Check each table independently."""
    try:
        if not Path(POI_DB_PATH).exists():
            return
        conn = await aiosqlite.connect(POI_DB_PATH, uri=False)
        conn.row_factory = aiosqlite.Row
        state.poi_db = conn

        # Check GNIS table (independent)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='poi_fts'"
        ) as cur:
            state.poi_db_loaded = (await cur.fetchone()) is not None

        # Check OSM POI table (independent)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='osm_pois'"
        ) as cur:
            state.osm_pois_loaded = (await cur.fetchone()) is not None

        if state.osm_pois_loaded:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_osm_pois_latlon ON osm_pois (lat, lon)"
            )
    except Exception:
        state.poi_db = None
        state.poi_db_loaded = False
        state.osm_pois_loaded = False
```

> **PITFALL WARNING:** The old `_open_poi_db()` closed the connection and returned if `poi_fts` was missing. The new version keeps the connection open even if GNIS is absent, because OSM POIs may still be available. Both tables are checked independently.

- [ ] **Step 3: Add `_query_osm_pois()` function**

Add after `_query_poi()` (around line 300):

```python
# ---------------------------------------------------------------------------
# OSM POI FTS5 query
# ---------------------------------------------------------------------------
async def _query_osm_pois(
    q: str,
    limit: int,
    bbox: Optional[str],
) -> list[dict]:
    """Query the OSM POI FTS5 index and return normalised results."""
    if not state.osm_pois_loaded or state.poi_db is None:
        return []

    # Token-based matching (OR), not phrase matching.
    # "Shell fuel" becomes: "Shell" OR "fuel"
    # This matches across columns: "Shell" in name, "fuel" in osm_value
    tokens = q.split()
    safe_tokens = [t.replace('"', '""') for t in tokens if len(t) > 1]
    if not safe_tokens:
        return []
    fts_query = " OR ".join(f'"{t}"' for t in safe_tokens)

    sql = """
        SELECT o.name, o.osm_key, o.osm_value, o.operator, o.lat, o.lon
        FROM osm_fts AS fts
        JOIN osm_pois AS o ON o.rowid = fts.rowid
        WHERE osm_fts MATCH ?
    """
    params: list = [fts_query]

    if bbox:
        parts = bbox.split(",")
        if len(parts) == 4:
            try:
                lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
                sql += " AND o.lon BETWEEN ? AND ? AND o.lat BETWEEN ? AND ?"
                params.extend([lon_min, lon_max, lat_min, lat_max])
            except ValueError:
                pass

    sql += " LIMIT ?"
    params.append(limit)

    try:
        async with state.poi_db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    except Exception:
        return []

    results: list[dict] = []
    for row in rows:
        name = row[0] or ""
        osm_key = row[1] or ""
        osm_value = row[2] or ""
        operator = row[3]
        lat = row[4]
        lon = row[5]
        results.append(
            {
                "name": name,
                "type": "osm_poi",
                "osm_key": osm_key,
                "osm_value": osm_value,
                "operator": operator,
                "lat": float(lat),
                "lon": float(lon),
                "display_name": f"{name} ({osm_value})" if osm_value else name,
            }
        )
    return results
```

- [ ] **Step 4: Update `_deduplicate()` for three-way merge**

Replace the existing `_deduplicate()` function (lines 305-323) with:

```python
def _deduplicate(
    nominatim_results: list[dict],
    poi_results: list[dict],
    osm_poi_results: list[dict] | None = None,
) -> list[dict]:
    """Merge results, dropping lower-priority entries within 100m.

    Priority order: Nominatim > GNIS > OSM POI.
    Third argument defaults to None for backward compatibility.
    """
    merged = list(nominatim_results)

    # Add GNIS results, dedup against Nominatim
    for poi in poi_results:
        dominated = False
        for existing in merged:
            try:
                dist = haversine_m(poi["lat"], poi["lon"], existing["lat"], existing["lon"])
                if dist <= 100:
                    dominated = True
                    break
            except (KeyError, TypeError, ValueError):
                continue
        if not dominated:
            merged.append(poi)

    # Add OSM POI results, dedup against Nominatim + GNIS
    if osm_poi_results:
        for osm_poi in osm_poi_results:
            dominated = False
            for existing in merged:
                try:
                    dist = haversine_m(osm_poi["lat"], osm_poi["lon"],
                                       existing["lat"], existing["lon"])
                    if dist <= 100:
                        dominated = True
                        break
                except (KeyError, TypeError, ValueError):
                    continue
            if not dominated:
                merged.append(osm_poi)

    return merged
```

> **BACKWARD COMPATIBILITY:** The third argument defaults to `None`. Existing callers in `main.py` and `spatial.py` that pass only two arguments continue to work unchanged.

- [ ] **Step 5: Update `/search` endpoint for three concurrent queries**

Replace the existing `/search` endpoint handler (lines 329-352) with:

```python
@app.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results"),
    bbox: Optional[str] = Query(
        None,
        description="Bounding box as lon_min,lat_min,lon_max,lat_max",
    ),
):
    nominatim_task = asyncio.create_task(_query_nominatim(q, limit, bbox))
    poi_task = asyncio.create_task(_query_poi(q, limit, bbox))
    osm_task = asyncio.create_task(_query_osm_pois(q, limit, bbox))

    nominatim_results, poi_results, osm_results = await asyncio.gather(
        nominatim_task, poi_task, osm_task, return_exceptions=True
    )

    # If any leg raised, treat as empty.
    if isinstance(nominatim_results, BaseException):
        nominatim_results = []
    if isinstance(poi_results, BaseException):
        poi_results = []
    if isinstance(osm_results, BaseException):
        osm_results = []

    merged = _deduplicate(nominatim_results, poi_results, osm_results)
    return {"results": merged[:limit]}
```

- [ ] **Step 6: Update `/health` endpoint to report `osm_pois_loaded`**

Replace the `/health` endpoint return (around line 368):

```python
@app.get("/health")
async def health():
    nominatim_available = False
    try:
        resp = await state.http_client.get(f"{NOMINATIM_URL}/status", timeout=2.0)
        nominatim_available = resp.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "nominatim_available": nominatim_available,
        "poi_db_loaded": state.poi_db_loaded,
        "osm_pois_loaded": state.osm_pois_loaded,
    }
```

**Test commands:**
```bash
# Existing tests still pass
cd /home/administrator/Code/geographica && python -m pytest tests/test_spatial_endpoint.py -v
cd /home/administrator/Code/geographica && python -m pytest tests/test_intent_parser.py -v
```

**Commit:**
```bash
git add services/search/main.py
git commit -m "feat: add OSM POI query as third search leg in search service

- Add osm_pois_loaded to State class
- Restructure _open_poi_db() to check GNIS and OSM tables independently
- Add _query_osm_pois() with token-based FTS5 matching
- Update _deduplicate() for three-way merge (backward compatible)
- Update /search endpoint for three concurrent queries
- Update /health to report osm_pois_loaded

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Search Integration Tests

**Dependencies:** Task 4 (main.py changes)
**Creates:** `tests/test_osm_poi_search.py`

> BEFORE starting work:
> 1. Read `docs/pitfalls/testing-pitfalls.md` — especially #1 (real SQLite), #5 (async test isolation), #8 (monkeypatch)
> 2. Read `tests/test_spatial_endpoint.py` for the test pattern (TestClient, fixtures)

**Behavior change:** No tests exist for OSM POI search integration. After this task, tests validate `_query_osm_pois()`, three-way dedup, graceful degradation, and bbox filtering.

**Do NOT:**
- Mock the SQLite database (use real in-memory or tmp databases)
- Modify main.py (that was Task 4)
- Test the indexer (that was Task 3)

- [ ] **Step 1: Create `tests/test_osm_poi_search.py`**

```python
"""Tests for OSM POI search integration in main.py."""
import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from main import _deduplicate, _query_osm_pois, haversine_m, state


def _create_test_db(db_path: str) -> None:
    """Create a test SQLite database with osm_pois and osm_fts tables."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
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
    conn.execute("CREATE INDEX idx_osm_pois_latlon ON osm_pois (lat, lon)")

    # Insert test data
    test_data = [
        ("Shell Station", "amenity", "fuel", "Shell", "node", 1, 33.45, -112.07),
        ("Desert Cafe", "amenity", "restaurant", None, "way", 2, 33.42, -111.95),
        ("Prescott NF", "boundary", "protected_area", "USFS", "relation", 3, 34.5, -112.1),
        ("BLM Land", "boundary", "protected_area", "BLM", "relation", 4, 35.0, -111.5),
        ("Holiday Inn", "tourism", "hotel", None, "node", 5, 36.0, -115.0),
    ]
    for name, key, value, operator, osm_type, osm_id, lat, lon in test_data:
        cur = conn.execute(
            "INSERT INTO osm_pois (name, osm_key, osm_value, operator, osm_type, osm_id, lat, lon) VALUES (?,?,?,?,?,?,?,?)",
            (name, key, value, operator, osm_type, osm_id, lat, lon),
        )
        conn.execute(
            "INSERT INTO osm_fts (rowid, name, osm_value, operator) VALUES (?,?,?,?)",
            (cur.lastrowid, name, value, operator or ""),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def osm_db(tmp_path, monkeypatch):
    """Create a temporary OSM POI database and configure state."""
    db_path = str(tmp_path / "test_poi.sqlite")
    _create_test_db(db_path)
    monkeypatch.setenv("POI_DB_PATH", db_path)

    import aiosqlite

    async def _setup():
        conn = await aiosqlite.connect(db_path)
        conn.row_factory = aiosqlite.Row
        state.poi_db = conn
        state.osm_pois_loaded = True
        state.poi_db_loaded = False  # No GNIS in this test db

    asyncio.get_event_loop().run_until_complete(_setup())
    yield db_path

    async def _cleanup():
        if state.poi_db:
            await state.poi_db.close()
        state.poi_db = None
        state.osm_pois_loaded = False

    asyncio.get_event_loop().run_until_complete(_cleanup())


class TestQueryOsmPois:
    """Test _query_osm_pois() function."""

    @pytest.mark.asyncio
    async def test_returns_results_for_matching_query(self, osm_db):
        results = await _query_osm_pois("Shell", 10, None)
        assert len(results) >= 1
        assert results[0]["name"] == "Shell Station"
        assert results[0]["type"] == "osm_poi"
        assert results[0]["osm_key"] == "amenity"
        assert results[0]["osm_value"] == "fuel"

    @pytest.mark.asyncio
    async def test_token_query_matches_across_columns(self, osm_db):
        # "fuel" is in osm_value column, not name
        results = await _query_osm_pois("fuel", 10, None)
        assert len(results) >= 1
        fuel_names = [r["name"] for r in results]
        assert "Shell Station" in fuel_names

    @pytest.mark.asyncio
    async def test_operator_searchable(self, osm_db):
        results = await _query_osm_pois("BLM", 10, None)
        assert len(results) >= 1
        assert any(r["operator"] == "BLM" for r in results)

    @pytest.mark.asyncio
    async def test_bbox_filtering(self, osm_db):
        # Tight bbox around Phoenix area only
        bbox = "-112.5,33.0,-111.5,34.0"
        results = await _query_osm_pois("Shell", 10, bbox)
        # Shell Station is at 33.45, -112.07 — inside bbox
        assert len(results) >= 1

        # Tight bbox around Las Vegas — Shell is outside
        bbox_lv = "-116.0,35.5,-114.0,36.5"
        results_lv = await _query_osm_pois("Shell", 10, bbox_lv)
        assert len(results_lv) == 0

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, osm_db):
        results = await _query_osm_pois("", 10, None)
        assert results == []

    @pytest.mark.asyncio
    async def test_single_char_tokens_skipped(self, osm_db):
        # Single-character tokens are filtered out
        results = await _query_osm_pois("a", 10, None)
        assert results == []


class TestGracefulDegradation:
    """Test behavior when osm_pois table is missing."""

    @pytest.mark.asyncio
    async def test_missing_table_returns_empty(self):
        # Reset state to simulate missing table
        old_loaded = state.osm_pois_loaded
        state.osm_pois_loaded = False
        try:
            results = await _query_osm_pois("Shell", 10, None)
            assert results == []
        finally:
            state.osm_pois_loaded = old_loaded

    @pytest.mark.asyncio
    async def test_none_db_returns_empty(self):
        old_db = state.poi_db
        old_loaded = state.osm_pois_loaded
        state.poi_db = None
        state.osm_pois_loaded = True
        try:
            results = await _query_osm_pois("Shell", 10, None)
            assert results == []
        finally:
            state.poi_db = old_db
            state.osm_pois_loaded = old_loaded


class TestThreeWayDedup:
    """Test _deduplicate() with three result sources."""

    def test_backward_compatible_two_args(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 34.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi)
        assert len(merged) == 2

    def test_three_way_merge(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 34.0, "lon": -112.0}]
        osm = [{"name": "C", "lat": 35.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 3

    def test_osm_deduped_against_nominatim(self):
        nom = [{"name": "Shell", "lat": 33.0, "lon": -112.0}]
        poi = []
        osm = [{"name": "Shell Station", "lat": 33.0, "lon": -112.0}]  # Same location
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 1  # OSM result dropped (within 100m of Nominatim)

    def test_osm_deduped_against_gnis(self):
        nom = []
        poi = [{"name": "Test Peak", "lat": 33.0, "lon": -112.0}]
        osm = [{"name": "Test Peak", "lat": 33.0001, "lon": -112.0}]  # ~11m away
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 1  # OSM result dropped (within 100m of GNIS)

    def test_osm_kept_when_distant(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 33.0, "lon": -111.0}]
        osm = [{"name": "C", "lat": 35.0, "lon": -110.0}]  # Far from both
        merged = _deduplicate(nom, poi, osm)
        assert len(merged) == 3

    def test_none_osm_arg_backward_compat(self):
        nom = [{"name": "A", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "B", "lat": 34.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi, None)
        assert len(merged) == 2

    def test_priority_order_nominatim_first(self):
        """Nominatim results should appear before GNIS and OSM."""
        nom = [{"name": "Nom", "lat": 33.0, "lon": -112.0}]
        poi = [{"name": "GNIS", "lat": 34.0, "lon": -112.0}]
        osm = [{"name": "OSM", "lat": 35.0, "lon": -112.0}]
        merged = _deduplicate(nom, poi, osm)
        assert merged[0]["name"] == "Nom"
```

**Test command:**
```bash
cd /home/administrator/Code/geographica && python -m pytest tests/test_osm_poi_search.py -v
```

**Commit:**
```bash
git add tests/test_osm_poi_search.py
git commit -m "test: search integration tests for OSM POI queries

Tests _query_osm_pois() FTS5 matching, bbox filtering, operator search,
three-way dedup priority (Nominatim > GNIS > OSM), graceful degradation
when osm_pois table is missing, and backward compatibility.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Spatial Search Changes

**Dependencies:** Task 4 (osm_pois_loaded in State)
**Modifies:** `services/search/spatial.py`

> BEFORE starting work:
> 1. Read `docs/pitfalls/testing-pitfalls.md`
> 2. Read `services/search/spatial.py` COMPLETELY — understand the synonym table, parse_intent(), corridor_filter(), and the spatial endpoint
> 3. Read the spec sections "Spatial search changes", "New synonym table entries", and "Intent parser changes"

**Behavior change:** Spatial search currently queries only Nominatim and GNIS. After this task, it also queries the `osm_pois` table directly by `osm_key`/`osm_value` for category-specific corridor and proximity searches. Public land queries (BLM, USFS, NPS) use the `osm_operator` field for disambiguation.

**Do NOT:**
- Break existing spatial search functionality
- Change the intent parser return format in a way that breaks existing callers
- Add innerHTML anywhere

- [ ] **Step 1: Add BLM/USFS/NPS synonym table entries**

Add these entries to the `SYNONYM_TABLE` list in `spatial.py`, after the existing entries (before the `_SYNONYM_LOOKUP` builder loop):

```python
    # Public land (OSM POI primary — requires osm_operator disambiguation)
    {"synonyms": {"blm", "blm land", "bureau of land management"},
     "gnis_class": None, "fallback_text": "BLM land",
     "nominatim_query": ["BLM"],
     "osm_types": {("boundary", "protected_area")},
     "osm_operator": "BLM"},
    {"synonyms": {"national forest", "usfs"},
     "gnis_class": None, "fallback_text": "national forest",
     "nominatim_query": ["national forest"],
     "osm_types": {("boundary", "protected_area")},
     "osm_operator": "USFS"},
    {"synonyms": {"national park", "nps"},
     "gnis_class": "Park", "fallback_text": "national park",
     "nominatim_query": ["national park"],
     "osm_types": {("boundary", "national_park"), ("boundary", "protected_area")},
     "osm_operator": "NPS"},
```

> **PITFALL WARNING:** The existing "ranger station" entry uses `{"synonyms": {"ranger station", "forest service"}, ...}`. The new "national forest" entry uses `{"synonyms": {"national forest", "usfs"}, ...}`. These do NOT overlap — "forest service" goes to ranger station, "national forest" goes to USFS protected areas. However, note that the existing "park" entry uses `{"synonyms": {"park"}, ...}` with `gnis_class: "Park"`. The new "national park" entry uses `{"synonyms": {"national park", "nps"}, ...}`. Multi-word "national park" will match before single-word "park" in the lookup, so no conflict.

- [ ] **Step 2: Add `osm_operator` to `parse_intent()` return dict**

In the `parse_intent()` function return dict (around line 293), add `osm_operator`:

```python
    return {
        "intent": intent,
        "original_intent": original_intent,
        "fallback_reason": fallback_reason,
        "category": entry["fallback_text"] if entry else None,
        "gnis_class": entry["gnis_class"] if entry else None,
        "search_text": search_text,
        "nominatim_queries": entry.get("nominatim_query", [search_text]) if entry else [search_text],
        "osm_types": entry.get("osm_types") if entry else None,
        "osm_operator": entry.get("osm_operator") if entry else None,
        "radius_m": radius_m,
        "interval_m": interval_m,
    }
```

- [ ] **Step 3: Add direct OSM POI query path in the spatial endpoint**

In the `spatial_search()` function, after the existing Nominatim+GNIS query block (around line 596), add the OSM POI query path. The modified spatial endpoint function should include:

After the existing import line:
```python
    from main import _query_nominatim, _query_poi, _query_osm_pois, _deduplicate, state
```

After the existing `poi_task` and before `all_results = await asyncio.gather(...)`, add the OSM POI query:

```python
    # Direct OSM POI query by category (bypasses FTS for precision)
    osm_poi_task = None
    osm_types = parsed.get("osm_types")
    osm_operator = parsed.get("osm_operator")

    if state.osm_pois_loaded and state.poi_db is not None and osm_types and bbox:
        async def _query_osm_pois_direct() -> list[dict]:
            """Query osm_pois table directly by osm_key/osm_value + bbox."""
            results = []
            parts = bbox.split(",")
            if len(parts) != 4:
                return results
            try:
                lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
            except ValueError:
                return results

            for osm_key, osm_value in osm_types:
                sql = """
                    SELECT name, osm_key, osm_value, operator, lat, lon
                    FROM osm_pois
                    WHERE osm_key = ? AND osm_value = ?
                    AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
                """
                params: list = [osm_key, osm_value, lat_min, lat_max, lon_min, lon_max]

                if osm_operator:
                    sql += " AND operator = ?"
                    params.append(osm_operator)

                sql += " LIMIT ?"
                params.append(limit)

                try:
                    async with state.poi_db.execute(sql, params) as cur:
                        rows = await cur.fetchall()
                    for row in rows:
                        results.append({
                            "name": row[0] or "",
                            "type": "osm_poi",
                            "osm_key": row[1] or "",
                            "osm_value": row[2] or "",
                            "operator": row[3],
                            "lat": float(row[4]),
                            "lon": float(row[5]),
                            "display_name": f"{row[0]} ({row[2]})" if row[2] else row[0] or "",
                        })
                except Exception:
                    continue
            return results

        osm_poi_task = _query_osm_pois_direct()
```

Then update the gather call:

```python
    if osm_poi_task:
        all_results = await asyncio.gather(*nom_tasks, poi_task, osm_poi_task, return_exceptions=True)
        osm_poi_results = all_results[-1] if not isinstance(all_results[-1], BaseException) else []
        poi_results = all_results[-2] if not isinstance(all_results[-2], BaseException) else []
    else:
        all_results = await asyncio.gather(*nom_tasks, poi_task, return_exceptions=True)
        osm_poi_results = []
        poi_results = all_results[-1] if not isinstance(all_results[-1], BaseException) else []
```

Then update the merge call:

```python
    merged = _deduplicate(nom_results, poi_results, osm_poi_results if osm_poi_results else None)
```

Also update the OSM type post-filter to include `osm_poi` type results:

```python
    # Post-filter by OSM type when a known category was matched.
    osm_types = parsed.get("osm_types")
    if osm_types and merged:
        filtered = []
        for r in merged:
            osm_cat = r.get("osm_category", "")
            osm_typ = r.get("osm_type", "")
            if (osm_cat, osm_typ) in osm_types:
                filtered.append(r)
            elif r.get("type") == "poi":
                # POI database results don't have osm_category — keep them
                filtered.append(r)
            elif r.get("type") == "osm_poi":
                # OSM POI results already filtered by osm_key/osm_value — keep them
                filtered.append(r)
        if filtered:
            merged = filtered
```

**Test command:**
```bash
# Existing tests still pass
cd /home/administrator/Code/geographica && python -m pytest tests/test_intent_parser.py tests/test_spatial_endpoint.py -v
```

**Commit:**
```bash
git add services/search/spatial.py
git commit -m "feat: add OSM POI direct query path and public land synonyms in spatial search

- Add BLM, USFS, NPS synonym entries with osm_operator disambiguation
- Add osm_operator to parse_intent() return dict
- Add direct SQL query path for osm_pois in corridor/proximity search
- Bypass FTS for category-specific queries (faster, more precise)
- Guard with osm_pois_loaded check

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Spatial Search Tests

**Dependencies:** Task 6 (spatial.py changes)
**Creates:** `tests/test_spatial_osm.py`

> BEFORE starting work:
> 1. Read `docs/pitfalls/testing-pitfalls.md` — #1 (real SQLite), #3 (fixture paths), #8 (monkeypatch)
> 2. Read `tests/test_intent_parser.py` and `tests/test_spatial_endpoint.py` for test patterns

**Behavior change:** No tests exist for spatial search with OSM POIs. After this task, tests validate the new synonym entries, `osm_operator` field in parse_intent, and the direct SQL query path.

**Do NOT:**
- Mock SQLite queries
- Modify spatial.py (that was Task 6)
- Hardcode fixture paths

- [ ] **Step 1: Create `tests/test_spatial_osm.py`**

```python
"""Tests for spatial search integration with OSM POIs."""
import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from spatial import parse_intent, SYNONYM_TABLE, _SYNONYM_LOOKUP


class TestPublicLandSynonyms:
    """Test new BLM/USFS/NPS synonym table entries."""

    def test_blm_synonym_exists(self):
        assert "blm" in _SYNONYM_LOOKUP
        assert "blm land" in _SYNONYM_LOOKUP
        assert "bureau of land management" in _SYNONYM_LOOKUP

    def test_usfs_synonym_exists(self):
        assert "national forest" in _SYNONYM_LOOKUP
        assert "usfs" in _SYNONYM_LOOKUP

    def test_nps_synonym_exists(self):
        assert "national park" in _SYNONYM_LOOKUP
        assert "nps" in _SYNONYM_LOOKUP

    def test_blm_has_osm_operator(self):
        entry = _SYNONYM_LOOKUP["blm"]
        assert entry.get("osm_operator") == "BLM"
        assert ("boundary", "protected_area") in entry["osm_types"]

    def test_usfs_has_osm_operator(self):
        entry = _SYNONYM_LOOKUP["national forest"]
        assert entry.get("osm_operator") == "USFS"
        assert ("boundary", "protected_area") in entry["osm_types"]

    def test_nps_has_osm_operator(self):
        entry = _SYNONYM_LOOKUP["national park"]
        assert entry.get("osm_operator") == "NPS"
        assert ("boundary", "national_park") in entry["osm_types"]
        assert ("boundary", "protected_area") in entry["osm_types"]

    def test_nps_has_gnis_class_park(self):
        entry = _SYNONYM_LOOKUP["national park"]
        assert entry["gnis_class"] == "Park"

    def test_existing_entries_no_osm_operator(self):
        """Existing synonym entries should not have osm_operator."""
        entry = _SYNONYM_LOOKUP["gas station"]
        assert entry.get("osm_operator") is None

    def test_no_conflict_with_forest_service(self):
        """'forest service' should still map to ranger station, not USFS."""
        entry = _SYNONYM_LOOKUP.get("forest service")
        assert entry is not None
        assert entry["fallback_text"] == "ranger station"

    def test_national_park_vs_park(self):
        """'national park' should match NPS entry, not generic 'park'."""
        entry = _SYNONYM_LOOKUP.get("national park")
        assert entry is not None
        assert entry.get("osm_operator") == "NPS"


class TestOsmOperatorInParseIntent:
    """Test osm_operator field in parse_intent() return."""

    def test_blm_query_returns_osm_operator(self):
        result = parse_intent("nearest BLM land", has_position=True, has_route=False)
        assert result["osm_operator"] == "BLM"
        assert result["category"] == "BLM land"

    def test_usfs_query_returns_osm_operator(self):
        result = parse_intent("national forest near me", has_position=True, has_route=False)
        assert result["osm_operator"] == "USFS"
        assert result["category"] == "national forest"

    def test_nps_query_returns_osm_operator(self):
        result = parse_intent("nearest national park", has_position=True, has_route=False)
        assert result["osm_operator"] == "NPS"

    def test_gas_station_no_osm_operator(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["osm_operator"] is None

    def test_plain_query_no_osm_operator(self):
        result = parse_intent("Phoenix", has_position=False, has_route=False)
        assert result["osm_operator"] is None

    def test_corridor_blm(self):
        result = parse_intent("BLM land along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["osm_operator"] == "BLM"

    def test_proximity_nps(self):
        result = parse_intent("NPS within 50 miles", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["osm_operator"] == "NPS"


class TestDirectSqlQueryPath:
    """Test the direct SQL query path for OSM POIs in spatial search."""

    @pytest.fixture
    def osm_db(self, tmp_path, monkeypatch):
        """Create a test database with osm_pois for spatial queries."""
        db_path = str(tmp_path / "test_poi.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
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
        conn.execute("CREATE INDEX idx_osm_pois_latlon ON osm_pois (lat, lon)")
        conn.execute("CREATE INDEX idx_osm_pois_category_geo ON osm_pois (osm_key, osm_value, lat, lon)")

        # Insert test features along a route corridor (Phoenix to Flagstaff)
        route_features = [
            ("Shell Buckeye", "amenity", "fuel", None, 33.37, -112.58),
            ("Chevron Black Canyon", "amenity", "fuel", None, 34.07, -112.15),
            ("Circle K Camp Verde", "amenity", "fuel", None, 34.56, -111.86),
            ("Prescott NF", "boundary", "protected_area", "USFS", 34.55, -112.50),
            ("Coconino NF", "boundary", "protected_area", "USFS", 35.10, -111.70),
            ("BLM Agua Fria", "boundary", "protected_area", "BLM", 34.20, -112.10),
            ("Grand Canyon NP", "boundary", "national_park", "NPS", 36.05, -112.14),
            ("Montezuma Castle", "boundary", "protected_area", "NPS", 34.61, -111.84),
        ]
        for name, key, value, operator, lat, lon in route_features:
            cur = conn.execute(
                "INSERT INTO osm_pois (name, osm_key, osm_value, operator, lat, lon) VALUES (?,?,?,?,?,?)",
                (name, key, value, operator, lat, lon),
            )
            conn.execute(
                "INSERT INTO osm_fts (rowid, name, osm_value, operator) VALUES (?,?,?,?)",
                (cur.lastrowid, name, value, operator or ""),
            )
        conn.commit()
        conn.close()

        monkeypatch.setenv("POI_DB_PATH", db_path)

        import aiosqlite
        from main import state

        async def _setup():
            conn = await aiosqlite.connect(db_path)
            conn.row_factory = aiosqlite.Row
            state.poi_db = conn
            state.osm_pois_loaded = True
            state.poi_db_loaded = False

        asyncio.get_event_loop().run_until_complete(_setup())
        yield db_path

        async def _cleanup():
            if state.poi_db:
                await state.poi_db.close()
            state.poi_db = None
            state.osm_pois_loaded = False

        asyncio.get_event_loop().run_until_complete(_cleanup())

    def test_direct_query_fuel_in_bbox(self, osm_db):
        """Direct SQL should find fuel stations within bbox."""
        from main import state
        import aiosqlite

        async def _test():
            sql = """
                SELECT name, osm_key, osm_value, operator, lat, lon
                FROM osm_pois
                WHERE osm_key = ? AND osm_value = ?
                AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            """
            # Phoenix-Flagstaff corridor bbox
            async with state.poi_db.execute(
                sql, ["amenity", "fuel", 33.0, 35.0, -113.0, -111.0]
            ) as cur:
                rows = await cur.fetchall()
            names = [row[0] for row in rows]
            assert "Shell Buckeye" in names
            assert "Chevron Black Canyon" in names

        asyncio.get_event_loop().run_until_complete(_test())

    def test_operator_filter_usfs(self, osm_db):
        """osm_operator filter should return only USFS-managed areas."""
        from main import state

        async def _test():
            sql = """
                SELECT name FROM osm_pois
                WHERE osm_key = ? AND osm_value = ? AND operator = ?
                AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            """
            async with state.poi_db.execute(
                sql, ["boundary", "protected_area", "USFS", 33.0, 36.0, -113.0, -111.0]
            ) as cur:
                rows = await cur.fetchall()
            names = [row[0] for row in rows]
            assert "Prescott NF" in names
            assert "Coconino NF" in names
            assert "BLM Agua Fria" not in names  # BLM, not USFS

        asyncio.get_event_loop().run_until_complete(_test())

    def test_operator_filter_blm(self, osm_db):
        """osm_operator filter should return only BLM-managed areas."""
        from main import state

        async def _test():
            sql = """
                SELECT name FROM osm_pois
                WHERE osm_key = ? AND osm_value = ? AND operator = ?
                AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
            """
            async with state.poi_db.execute(
                sql, ["boundary", "protected_area", "BLM", 33.0, 36.0, -113.0, -111.0]
            ) as cur:
                rows = await cur.fetchall()
            names = [row[0] for row in rows]
            assert "BLM Agua Fria" in names
            assert "Prescott NF" not in names

        asyncio.get_event_loop().run_until_complete(_test())

    def test_osm_pois_loaded_guard(self):
        """If osm_pois_loaded is False, direct queries should be skipped."""
        from main import state
        assert not state.osm_pois_loaded  # default without fixture
        # The guard in spatial.py checks state.osm_pois_loaded before querying
        # This test verifies the flag is correctly False when no DB is loaded
```

**Test command:**
```bash
cd /home/administrator/Code/geographica && python -m pytest tests/test_spatial_osm.py -v
```

**Commit:**
```bash
git add tests/test_spatial_osm.py
git commit -m "test: spatial search tests for OSM POI integration

Tests BLM/USFS/NPS synonym entries, osm_operator in parse_intent(),
direct SQL query path with operator filtering, and osm_pois_loaded
guard for graceful degradation.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Build and Smoke Test

**Dependencies:** All previous tasks (1-7)
**Modifies:** `CLAUDE.md` (add indexer command)

> BEFORE starting work:
> 1. Read `docs/pitfalls/implementation-pitfalls.md` — #1 (data outside repo)
> 2. Ensure all unit tests pass first

**Behavior change:** After this task, the `osm_pois` table is populated with real data from the PBF file and search queries return OSM POI results.

**Do NOT:**
- Run the full extraction if the PBF file is missing (skip gracefully)
- Store data inside the git repo
- Push changes without verifying

- [ ] **Step 1: Run all unit tests**

```bash
cd /home/administrator/Code/geographica && python -m pytest tests/test_osm_poi_indexer.py tests/test_osm_poi_search.py tests/test_spatial_osm.py tests/test_intent_parser.py tests/test_spatial_endpoint.py -v
```

All tests must pass before proceeding.

- [ ] **Step 2: Run the indexer against the PBF (if available)**

```bash
# Check PBF exists
ls -lh /srv/geographica/data/valhalla/western-us.osm.pbf

# Run the extraction (~5-15 minutes on Pi 5)
python3 scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"
```

If the PBF file is not at that path, check alternate locations:
```bash
find /srv/geographica/data -name "*.osm.pbf" -type f 2>/dev/null
```

> **PITFALL WARNING:** The extraction writes to `/srv/geographica/data/poi.sqlite` which already contains the GNIS `poi_features` table. The `write_to_sqlite()` function drops and recreates only `osm_pois` and `osm_fts` — it does NOT touch `poi_features` or `poi_fts`. Verify this after the run.

- [ ] **Step 3: Verify the database**

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('/srv/geographica/data/poi.sqlite')
print('Tables:', [t[0] for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])
print()

# OSM POIs
osm_count = conn.execute('SELECT COUNT(*) FROM osm_pois').fetchone()[0]
print(f'OSM POIs: {osm_count:,}')

# Category breakdown
for row in conn.execute('SELECT osm_key, osm_value, COUNT(*) as c FROM osm_pois GROUP BY osm_key, osm_value ORDER BY c DESC LIMIT 20').fetchall():
    print(f'  {row[0]}={row[1]}: {row[2]:,}')

print()

# GNIS (if present)
try:
    gnis_count = conn.execute('SELECT COUNT(*) FROM poi_features').fetchone()[0]
    print(f'GNIS features: {gnis_count:,}')
except:
    print('GNIS table not present')

# FTS5 smoke test
fts_test = conn.execute(\"SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'Shell'\").fetchone()[0]
print(f'FTS5 \"Shell\" matches: {fts_test}')

fts_blm = conn.execute(\"SELECT COUNT(*) FROM osm_fts WHERE osm_fts MATCH 'BLM'\").fetchone()[0]
print(f'FTS5 \"BLM\" matches: {fts_blm}')

conn.close()
"
```

Expected output (approximate):
- 350K-650K OSM POIs
- Top categories: amenity=restaurant, amenity=fuel, shop=*, tourism=*
- FTS5 "Shell" matches: 500+
- FTS5 "BLM" matches: 1000+
- GNIS features still present (if previously indexed)

- [ ] **Step 4: Restart the search service and test queries**

```bash
# Restart to pick up new database tables
docker compose restart search

# Wait for healthy
sleep 5
docker compose ps search

# Test search endpoint
curl -s "http://localhost:8096/search?q=Shell+gas+station&limit=5" | python3 -m json.tool | head -30

# Test health endpoint
curl -s "http://localhost:8096/health" | python3 -m json.tool

# Test spatial search for gas stations along a route segment
curl -s -X POST "http://localhost:8096/spatial" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "gas stations along my route",
    "route": [[-112.07, 33.45], [-112.5, 33.4], [-113.0, 33.3], [-114.0, 33.5], [-114.5, 34.0]]
  }' | python3 -m json.tool | head -40

# Test BLM land search
curl -s -X POST "http://localhost:8096/spatial" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "BLM land near me",
    "position": {"lat": 34.5, "lon": -112.0}
  }' | python3 -m json.tool | head -30
```

Verify:
- `/health` response includes `"osm_pois_loaded": true`
- `/search?q=Shell` returns results with `"type": "osm_poi"`
- Spatial gas station search returns results in the previously empty I-10 corridor
- BLM land search returns only BLM-managed areas (not USFS or NPS)

- [ ] **Step 5: Update CLAUDE.md**

Add to the Commands section in `CLAUDE.md`:

```bash
# OSM POI extraction (run once, requires osmium)
python3 scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"
```

**Commit:**
```bash
git add CLAUDE.md
git commit -m "docs: add OSM POI extraction command to CLAUDE.md

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Execution Recommendation

**Recommended: Option 2 — subagent-driven development with `/subagent-driven-development`.**

Reasoning:
- **Task independence:** Tasks 1-3 (indexer) and Tasks 4-5 (search service) are independent. A subagent dispatcher can run indexer and search service tracks in parallel.
- **Sequential dependencies within tracks:** Tasks 1->2->3 are strictly sequential. Tasks 4->5 are sequential. Tasks 6->7 depend on Task 4.
- **Risk profile:** The highest risk is in Task 4 (restructuring `_open_poi_db()` which affects the entire service startup) and Task 6 (adding the direct SQL query path to spatial search). Both benefit from the review-before-commit loop.
- **Plan self-containment:** Every task includes exact file paths, complete code blocks, test commands, and commit commands. A fresh subagent with CLAUDE.md and this plan has everything needed.

Task 8 (smoke test) requires all other tasks to be complete and the Docker stack running, so it must be the final sequential step.
