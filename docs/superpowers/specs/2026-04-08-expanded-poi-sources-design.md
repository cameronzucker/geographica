# Expanded POI Sources: OSM Amenity & Public Land Extraction

**Date:** 2026-04-08
**Status:** Design approved
**Author:** Cameron Zucker + Claude
**Depends on:** Phase 2a natural language spatial search (complete)

## Overview

Supplement the existing GNIS-only POI database with commercial amenities and public land boundaries extracted from the OSM PBF file already on disk. This fills the critical gap where spatial search returns no results for commercial categories (gas, food, lodging) in rural areas — notably the 240-mile gap on I-10 between Buckeye and Blythe.

The extraction uses `osmium` CLI (already installed, v1.18.0) to filter and export features from the 3.1GB `western-us.osm.pbf`, then a Python script writes them to a new `osm_pois` table in the existing `poi.sqlite` database. The search service queries the new table as a third leg alongside Nominatim and GNIS.

## Problem

The current spatial search has two data sources:
- **Nominatim** — live queries against the local OSM database. Good for named places, but commercial POI coverage is sparse in rural Western US.
- **GNIS** — 304K geographic features (summits, springs, bridges). No commercial POIs at all.

Searching "gas stations along my route" between Phoenix and LA produces a 240-mile gap with no results. Gas stations exist there — they're in the OSM data — but they're not in our search index. The same problem affects restaurants, hotels, and all other commercial categories.

Additionally, public land boundaries (BLM, USFS, NPS, state lands) are in the OSM PBF but not searchable. In the Western US, public/private land is often checkerboarded with no markings on the ground.

## Architecture

### Extraction pipeline

```
western-us.osm.pbf (3.1 GB, on disk)
    │
    ▼
osmium extract --bbox (clip to project bounding box)
    │
    ▼
clipped.pbf
    │
    ▼
osmium tags-filter (amenity=* shop=* tourism=* ...)
    │
    ▼
filtered.pbf (~20-50 MB)
    │
    ▼
osmium export -f geojsonseq (full geometries — centroids computed in Python step)
    │
    ▼
features.geojsonseq (line-delimited GeoJSON)
    │
    ▼
build_osm_pois.py (parse, normalize, dedup, insert)
    │
    ▼
poi.sqlite → osm_pois table + osm_fts index
    │
    ▼
cleanup intermediate files
```

`osmium tags-filter` does not accept a bbox argument. The bbox is applied first via `osmium extract` to avoid processing features outside the project area.

### Search integration

```
User query: "gas stations along my route"
    │
    ▼
spatial.py intent parser → route_corridor, category: gas
    │
    ├── Nominatim query (existing, unchanged)
    ├── GNIS POI query (existing, unchanged)
    └── OSM POI query (NEW: WHERE osm_key='amenity' AND osm_value='fuel')
    │
    ▼
merge + 100m haversine dedup (Nominatim > GNIS > OSM priority)
    │
    ▼
results with the 240-mile gap filled
```

## Extraction script

### New script: `scripts/build_osm_pois.py`

Separate from the GNIS indexer (`build_poi_index.py`). Different data source (local PBF vs internet download), different invocation context, independent rebuild cycle.

### CLI interface

```bash
python3 scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"
```

- `--pbf`: path to the OSM PBF file
- `--output`: path to the existing `poi.sqlite` (creates `osm_pois` table alongside `poi_features`)
- `--bbox`: bounding box filter (same as GNIS indexer)
- `--geojsonseq`: optional argument that accepts pre-extracted GeoJSONSeq, skipping the osmium steps. Used by tests and for debugging.
- Idempotent: drops and recreates `osm_pois` and `osm_fts` tables on each run

### Tag filter list

```
amenity=*
shop=*
tourism=*
leisure=*
healthcare=*
highway=rest_area
highway=services
boundary=protected_area
boundary=national_park
```

Features must have at least one of: `name`, `brand`, or `operator` tag. The display name is resolved as: `name || brand || operator` (first non-null). This is critical for commercial POIs where OSM contributors tag `brand=Shell` without setting `name`. Features with none of these three tags are skipped.

### Operator normalization

```python
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
```

Operators not in the normalization table are kept as-is (e.g., "California Department of Parks and Recreation" retains its full name). Normalization is case-sensitive to avoid false matches.

### Centroid computation

`osmium export` outputs full geometries (polygons, multipolygons) — not centroids. The Python parsing step computes centroids:

- **Point features**: use coordinates directly
- **Polygon/MultiPolygon features**: compute centroid using the Shapely library (`shapely.geometry.shape(geojson_geom).centroid`) for proper geometric centroids. Shapely handles concave polygons, multipolygons, and irregular boundaries correctly. Add `shapely` to `scripts/requirements.txt`.
- **LineString features** (rare for POIs): use midpoint

### Index-time deduplication

The same business can appear in OSM as both a node (point) and a way (building outline). During insertion, skip any feature with the same name within a distance threshold of an already-inserted feature. Dedup radius is 50m for commercial POIs (`amenity`, `shop`) and 100m for natural/boundary features. This prevents incorrectly merging two Shell stations on opposite sides of a highway interchange while still catching node+way duplicates for the same business.

Performance: a naive all-pairs check is O(n²) — too slow for 600K features. Instead, use a dict keyed by `(name_lower, round(lat, 3), round(lon, 3))` where rounding to 3 decimal places (~111m) approximates the 100m dedup radius. If the key exists, check haversine distance; if within 100m, skip. This makes dedup effectively O(n) with constant-time lookups.

### Estimated output

| Category | Estimated features |
|----------|-------------------|
| `amenity=*` | ~200-400K |
| `shop=*` | ~50-100K |
| `tourism=*` | ~20-50K |
| `leisure=*` | ~30-60K |
| `healthcare=*` | ~5-10K |
| `highway=rest_area\|services` | ~1-2K |
| `boundary=protected_area\|national_park` | ~37K |
| **Total** | **~350-650K named features** |

Database size increase: ~30-50MB added to the existing 38MB `poi.sqlite`. Trivial on an 896GB SSD.

## Database schema

### New table: `osm_pois`

```sql
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
);

CREATE VIRTUAL TABLE osm_fts USING fts5(
    name, osm_value, operator,
    content=osm_pois,
    content_rowid=id
);

CREATE INDEX idx_osm_pois_latlon ON osm_pois (lat, lon);

CREATE INDEX idx_osm_pois_category_geo ON osm_pois (osm_key, osm_value, lat, lon);
```

Compound index serves spatial.py's direct SQL queries that filter by category + bounding box simultaneously. The simple lat/lon index is kept for queries that don't filter by category.

- Separate table and FTS5 index from GNIS (`poi_features` / `poi_fts`)
- `osm_key`/`osm_value`: the OSM tag (e.g., `amenity`/`fuel`, `boundary`/`protected_area`)
- `operator`: managing agency for public lands, brand name for commercial, NULL if absent
- `osm_type` (node/way/relation) and `osm_id` enable tracing features back to source OSM objects for debugging data quality issues. The GeoJSONSeq export from osmium includes these as `@type` and `@id` properties.
- Lat/lon index for corridor/proximity bbox queries
- FTS5 indexes `name`, `osm_value`, and `operator` for full-text search (so "BLM" and "Shell" are searchable)

### Existing table unchanged

```sql
-- GNIS features (unchanged)
CREATE TABLE poi_features (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    class TEXT,
    state TEXT,
    county TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL
);
```

Both tables coexist in the same `poi.sqlite` file. The GNIS indexer and OSM indexer can be run independently in any order.

## Search service changes

### New query function in `main.py`

Add `_query_osm_pois()` as a third query leg, same pattern as `_query_poi()`:

```python
async def _query_osm_pois(
    q: str,
    limit: int,
    bbox: Optional[str],
) -> list[dict]:
    """Query the OSM POI FTS5 index and return normalised results."""
    if not state.osm_pois_loaded or state.poi_db is None:
        return []

    # Token-based matching, not phrase matching.
    # "Shell fuel" becomes: Shell OR fuel
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
    # ... bbox filtering, same pattern as _query_poi()
```

Phrase queries (`"Shell fuel station"`) would require all three words in sequence within a single column, which fails when terms span `name` and `osm_value`. Token-based OR matching finds results where any indexed column contains any of the search terms. For category-specific spatial searches, spatial.py uses direct SQL on `osm_key`/`osm_value` columns instead of FTS — avoiding the text matching problem entirely.

Results returned with `type: "osm_poi"` and include `osm_key`, `osm_value`, `operator` fields.

### Updated `/search` endpoint

The existing endpoint runs all three queries concurrently:

```python
nominatim_task = asyncio.create_task(_query_nominatim(q, limit, bbox))
poi_task = asyncio.create_task(_query_poi(q, limit, bbox))
osm_task = asyncio.create_task(_query_osm_pois(q, limit, bbox))

nominatim_results, poi_results, osm_results = await asyncio.gather(
    nominatim_task, poi_task, osm_task, return_exceptions=True
)
```

Dedup cascade in `_deduplicate()`: Nominatim results are authoritative (kept first), then GNIS, then OSM POIs. Any OSM POI within 100m of a Nominatim or GNIS result is dropped. The updated function signature:

```python
def _deduplicate(
    nominatim_results: list[dict],
    poi_results: list[dict],
    osm_poi_results: list[dict] | None = None,
) -> list[dict]:
```

Third argument defaults to None for backward compatibility. Existing callers in main.py and spatial.py do not need changes until they want to include OSM POI results.

### Startup changes

Add `osm_pois_loaded: bool = False` to the `State` class alongside the existing `poi_db_loaded` field.

In `main.py` lifespan, replace the existing startup logic with a restructured version that opens the database file if it exists, then checks each table independently:

```python
# Open poi.sqlite if file exists — check each table independently
async def _open_poi_db() -> None:
    try:
        if not Path(POI_DB_PATH).exists():
            return
        conn = await aiosqlite.connect(POI_DB_PATH)
        conn.row_factory = aiosqlite.Row
        state.poi_db = conn

        # Check GNIS table
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='poi_fts'"
        ) as cur:
            state.poi_db_loaded = (await cur.fetchone()) is not None

        # Check OSM POI table (independent of GNIS)
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

The database connection opens based on file existence, then each table is checked independently. This allows `build_osm_pois.py` to run before or after the GNIS indexer — either table can be present without the other.

Graceful degradation: if `osm_pois` table doesn't exist (indexer hasn't been run), `_query_osm_pois()` returns empty lists. No crash, no startup failure. The health endpoint reports `osm_pois_loaded` status.

## Spatial search changes

### Direct OSM POI queries in `spatial.py`

For corridor and proximity searches, `spatial.py` can query the `osm_pois` table directly by `osm_key`/`osm_value` within the search bbox, bypassing FTS entirely for category-specific queries:

```python
# Guard: skip if osm_pois table not loaded
if not state.osm_pois_loaded:
    osm_results = []
else:
    # For corridor search: gas stations along route
    # osm_types from synonym table: {("amenity", "fuel"), ("shop", "gas")}
    sql = """
        SELECT name, osm_key, osm_value, operator, lat, lon
        FROM osm_pois
        WHERE osm_key = ? AND osm_value = ?
        AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?
    """
    params = [osm_key, osm_value, lat_min, lat_max, lon_min, lon_max]

    # If synonym entry has osm_operator (e.g., "BLM"), add operator filter
    if synonym_entry.get("osm_operator"):
        sql += " AND operator = ?"
        params.append(synonym_entry["osm_operator"])
```

This is faster and more precise than FTS for category searches — no false positives from text matching. Results merge with Nominatim results using the same haversine dedup.

### New synonym table entries for public land

```python
{"synonyms": {"blm", "blm land", "bureau of land management"},
 "gnis_class": None,
 "fallback_text": "BLM land",
 "nominatim_query": ["BLM"],
 "osm_types": {("boundary", "protected_area")},
 "osm_operator": "BLM"},

{"synonyms": {"national forest", "forest service", "usfs"},
 "gnis_class": None,
 "fallback_text": "national forest",
 "nominatim_query": ["national forest"],
 "osm_types": {("boundary", "protected_area")},
 "osm_operator": "USFS"},

{"synonyms": {"national park", "nps"},
 "gnis_class": "Park",
 "fallback_text": "national park",
 "nominatim_query": ["national park"],
 "osm_types": {("boundary", "national_park"), ("boundary", "protected_area")},
 "osm_operator": "NPS"},
```

### New `osm_operator` field in synonym table

The `osm_operator` field is optional — only used for public land queries where the `osm_value` (`protected_area`) is shared across many agencies. When present, the OSM POI query adds `AND operator = ?` to disambiguate BLM from USFS from NPS.

Existing synonym entries without `osm_operator` are unaffected. The field defaults to `None`.

### Intent parser changes

Add `osm_operator` to the `parse_intent()` return dict: `'osm_operator': entry.get('osm_operator') if entry else None`. This flows through to the corridor/proximity query functions where it's used as an optional `AND operator = ?` filter.

## Testing

### Unit tests

**`tests/test_osm_poi_indexer.py`** — Indexer tests:
- Parses a minimal GeoJSONSeq fixture (5-10 features covering: point amenity, polygon with centroid, protected area with operator, unnamed feature to skip)
- Operator normalization: "US Bureau of Land Management" → "BLM", unknown operators kept as-is
- Bbox filtering: features outside bbox are excluded
- Dedup: same name within 100m produces one row, not two
- Schema: `osm_pois` and `osm_fts` tables created correctly
- Idempotent: running twice doesn't produce duplicates (table is dropped and recreated)

**`tests/test_osm_poi_search.py`** — Search integration tests:
- `_query_osm_pois()` returns results matching FTS query
- Bbox filtering works on OSM POI queries
- Results include `osm_key`, `osm_value`, `operator` fields
- Empty/missing table returns empty list (graceful degradation)
- Dedup across Nominatim + GNIS + OSM POI: same-location results merged correctly

**`tests/test_spatial_osm.py`** — Spatial search with OSM POIs:
- Corridor search queries OSM POI table by `osm_key`/`osm_value`
- `osm_operator` filter works for public land queries (BLM vs USFS)
- Proximity search returns OSM POI results sorted by distance
- Synonym table entries with `osm_operator` field produce correct queries

### Test fixtures

`tests/fixtures/test_osm_features.geojsonseq` — Derived from actual `osmium export` output on a small PBF extract. Run osmium on a ~1km² area, capture 10-15 representative lines covering: point amenity, polygon building, protected area relation, brand-only feature, unnamed feature. This ensures the fixture matches real osmium property format (flat properties with `@type`, `@id` metadata). Small enough to commit (~2KB).

### Integration test

Run the indexer against the GeoJSONSeq fixture (skipping the osmium steps), then query the resulting database through the search service. Validates the pipeline from parsed features to search results.

### Not tested (manual QA)

- Full PBF extraction (3.1GB, ~10 min) — smoke test during deployment
- Result quality for the Phoenix-to-LA corridor gap — manual verification that gas stations now appear in the 240-mile gap
- Public land search results — manual verification that "BLM land near me" returns correct results

## CLAUDE.md updates

Add to the Commands section:

```bash
# OSM POI extraction (run once, requires osmium)
python3 scripts/build_osm_pois.py \
  --pbf /srv/geographica/data/valhalla/western-us.osm.pbf \
  --output /srv/geographica/data/poi.sqlite \
  --bbox "-124.8,31.3,-102.0,49.0"
```
