# Bug Hunt Report: Corridor Query Returns Too Few Results

## Scope

**Files analyzed:**
- `services/search/spatial.py` (full file, 589 lines) -- intent parser, synonym table, corridor math, FastAPI endpoint
- `services/search/main.py` (full file, 925 lines) -- `_query_nominatim`, `_query_poi`, deduplication, admin/pipeline endpoints
- `scripts/build_poi_index.py` (full file, 269 lines) -- GNIS data pipeline that builds poi.sqlite
- `frontend/app.js` (search-relevant sections) -- how corridor queries are constructed and sent
- `nginx/nginx.conf` (search proxy) -- request routing
- `docker-compose.yml` -- Nominatim 5.2.0 (mediagis) with local OSM PBF
- Nominatim API documentation -- /search endpoint parameters, special phrases, limits

**Approach:** Traced the full data flow from user typing "gas stations every 50 miles along my route" through intent parsing, synonym resolution, Nominatim query construction, POI query, corridor filtering, and result return. Analyzed each stage for data loss.

## Bugs

### Bug 1: Nominatim limit=20 but API maximum is 40, and 20 is insufficient for 600 km corridor search
**Location:** `services/search/spatial.py:528`
**Severity:** significant
**Evidence:** The code hardcodes `limit = 20` for the Nominatim query. However:
1. Nominatim's API supports `limit` up to 40. For a 600 km route corridor, 20 results is far too few even at maximum -- Nominatim returns "a collection of the best matches" not an exhaustive list, so even limit=40 will be inadequate for long corridors.
2. The corridor bbox for Phoenix-to-Long Beach is roughly 4 degrees wide by 2 degrees tall. With `bounded=1`, Nominatim searches only within this box, but still returns at most 20 "best matches" for the free-text query. For a category like "gas station" that has hundreds of instances in this area, 20 is a severe bottleneck.
**Impact:** Even if Nominatim returns 20 gas stations for the bbox, most will cluster near population centers (Phoenix, LA). After corridor_filter narrows to within 2 km of the route and interval_filter picks one per 50-mile segment, only 1-3 results survive from 20 candidates. A 600 km route with 50-mile intervals needs ~7-8 results, requiring 50-100+ candidates to feed the corridor filter.

### Bug 2: Single Nominatim query with free-text "gas station" -- Nominatim returns dramatically different counts for different phrasings
**Location:** `services/search/spatial.py:509` and `services/search/main.py:197-198`
**Severity:** critical
**Evidence:** The synonym table maps "gas station" -> `fallback_text: "gas station"`. This `fallback_text` becomes `search_text` which is passed directly to `_query_nominatim` as the `q` parameter. The user reported: querying "gas station" returns 1 result; querying "fuel" returns 20.

This happens because Nominatim's special phrase system maps "fuel" directly to `amenity=fuel` (a recognized OSM tag), triggering a category-aware search that returns many POIs. But "gas station" is a compound phrase that Nominatim tries to geocode as a place name (like "Gas Station Road"), not as a category. The synonym table correctly identifies "gas station" as a synonym for fuel, but then passes "gas station" (the `fallback_text`) to Nominatim instead of using the term Nominatim actually understands.

The fix requires the synonym table to specify what Nominatim should receive, which is often different from the human-readable category name. For fuel, Nominatim understands "fuel", "petrol", "petrol station", "fuel station", "gas" -- but not "gas station" as a category.
**Impact:** This is the primary cause of the reported bug. The entire downstream pipeline (corridor filter, interval filter) starves for candidates because the Nominatim query itself returns ~1 result instead of ~20.

### Bug 3: Only one Nominatim query per search -- no multi-term fan-out for categories
**Location:** `services/search/spatial.py:528-533`
**Severity:** significant
**Evidence:** Even when the synonym table correctly identifies a category, only one Nominatim query is issued with one search term. Nominatim's special phrases have specific triggers -- "fuel" works but "gas station" doesn't, "fast food" works but "restaurant" might not find fast food places. A single query with one term will miss POIs tagged differently in OSM.

For robust corridor search, the code should issue multiple Nominatim queries with different phrasings (e.g., for the fuel category: query "fuel" AND "petrol station") and merge the results. Alternatively, use Nominatim's structured query with the `amenity` parameter (e.g., `amenity=fuel` instead of `q=gas station`), which directly maps to OSM tags without relying on special phrase matching.
**Impact:** Even with the correct search term, a single query returns at most 40 results (Nominatim hard cap). For a 600 km corridor, this is often insufficient.

### Bug 4: POI database (GNIS) has no commercial POIs -- the "second source" contributes zero results for road-trip queries
**Location:** `services/search/spatial.py:528-537` (queries both sources), `scripts/build_poi_index.py` (data source), `services/search/spatial.py:31-33` (synonym table entries with `gnis_class: None`)
**Severity:** significant
**Evidence:** The spatial search queries both Nominatim and the POI FTS5 database in parallel. But `build_poi_index.py` downloads GNIS (Geographic Names Information System) data, which contains geographic features like summits, springs, schools, churches, dams, bridges, trails -- NOT commercial POIs. The synonym table correctly marks commercial categories with `gnis_class: None`:
```python
{"synonyms": {"gas station", "fuel", "gas"}, "gnis_class": None, ...}
{"synonyms": {"restaurant", "food", "eat", "dining"}, "gnis_class": None, ...}
{"synonyms": {"hotel", "motel", "lodging"}, "gnis_class": None, ...}
```

When the user searches "gas stations along my route", `_query_poi` runs an FTS5 search for "gas station" against GNIS data. GNIS has no gas stations, so this always returns 0 results. The only data source is Nominatim, making Bug 2's single-query limitation even more severe.

For geographic features (summits, springs, airports), the POI database provides supplementary results. But for the primary road-trip use case (fuel, food, lodging), it contributes nothing.
**Impact:** The system has effectively one data source for the most common corridor queries, halving its resilience to poor Nominatim results.

### Bug 5: Corridor bbox margin is 0.02 degrees (~2.2 km), matching CORRIDOR_WIDTH_M, but Nominatim `bounded=1` clips results to this tight box
**Location:** `services/search/spatial.py:514-518` (bbox construction) and `services/search/main.py:206-208` (bounded=1)
**Severity:** minor
**Evidence:** The corridor bbox is computed with `margin = 0.02` (~2.2 km), which matches the `CORRIDOR_WIDTH_M = 2_000` constant. This bbox is then passed to `_query_nominatim`, which sets `bounded=1`, restricting Nominatim to only return results inside this box. The margin is exactly equal to the corridor width, leaving zero buffer for Nominatim's geocoding imprecision (POI coordinates in OSM can be the building centroid, not the road-facing entrance).

More importantly, this tight bbox interacts badly with Nominatim's limit. A tight bbox over a 600 km route covers a huge total area (the bounding rectangle of the route), but `bounded=1` means Nominatim only returns POIs inside it. With limit=20, Nominatim picks 20 "best" from this entire rectangle, which may cluster in cities rather than distributing along the route.
**Impact:** Minor on its own (the margin is barely too tight), but compounds with the limit issue. The bbox itself is not the bottleneck -- the limit is.

### Bug 6: `fallback_text` is used as Nominatim search term -- semantic mismatch
**Location:** `services/search/spatial.py:30-58` (synonym table) and `services/search/spatial.py:106-107`
**Severity:** critical (same root cause as Bug 2, but this is the structural issue)
**Evidence:** The synonym table has one field `fallback_text` that serves two purposes:
1. The human-readable category label shown in the UI (e.g., "gas station" in the subtitle "Gas station along route")
2. The search text sent to Nominatim's `q` parameter

These are different requirements. The UI label should be "gas station" (what humans say). The Nominatim query should be "fuel" (what Nominatim's special phrase system recognizes). The code at line 106-107:
```python
if normalized in _SYNONYM_LOOKUP:
    entry = _SYNONYM_LOOKUP[normalized]
    return entry, entry["fallback_text"]
```
returns `fallback_text` as the `search_text`, which is then used as Nominatim's `q` parameter at `spatial.py:509` and `main.py:198`.

The synonym table needs a separate field (e.g., `nominatim_terms`) that specifies the actual search terms Nominatim should receive, independent of the display label.
**Impact:** Every synonym entry where `fallback_text` differs from what Nominatim recognizes as a special phrase will produce degraded results. "gas station", "rest area", "fire station", "police station", "campground" -- all compound phrases that may or may not be recognized by Nominatim's special phrase list.

## Design Concerns

### Nominatim is fundamentally wrong for exhaustive category search along a corridor

Nominatim is a geocoder -- it turns text into coordinates. It is not a spatial POI database. The Nominatim documentation explicitly says: for exhaustive data retrieval, use the Overpass API. Nominatim returns "a collection of the best matches" with a hard cap of 40 results. For a corridor search that needs to find all gas stations across 600 km, Nominatim will always be lossy.

**Options to consider:**
1. **Segment the corridor into tiles and issue multiple Nominatim queries** -- divide the route into ~50 km segments, compute a small bbox for each, query Nominatim with `bounded=1` for each segment. Merge and deduplicate. This works within Nominatim's design but multiplies API calls.
2. **Use Nominatim's structured query with `amenity` parameter** -- instead of `q=gas station`, use `amenity=fuel` with a viewbox. This directly triggers OSM tag matching without relying on special phrase recognition.
3. **Build a local commercial POI database from OSM data** -- extract amenity nodes from the same PBF file used for Nominatim import. This would give the POI FTS5 database actual fuel stations, restaurants, hotels. The GNIS-only approach leaves a massive gap for the most common search categories.
4. **Use Overpass API** -- but this requires internet access, which contradicts the offline-first design.

### The interval filter algorithm is O(n*m) and picks suboptimal results

`corridor_filter` at line 444-459: the interval filter iterates all results for every interval marker. For each marker, it picks the result with the smallest absolute distance difference from the marker position. This means a single POI near the midpoint between two markers could be selected for both markers. The `if best and best not in filtered` check prevents duplicates, but the second marker then gets no result at all. A greedy-forward algorithm would be more appropriate.

### The 2 km corridor width is extremely tight for highway travel

`CORRIDOR_WIDTH_M = 2_000` (2 km). Interstate gas stations are often 0.5-1 km off the highway, but in rural areas, the nearest fuel can be in a town 5-10 km from the interstate. For an "emergency fuel" corridor search, 2 km will miss many viable options. This should perhaps be configurable or default higher (5-10 km) for fuel/essential categories.

### FTS5 search for category names against GNIS produces noise

When the user searches "gas station", `_query_poi` runs FTS5 for `"gas station"` against GNIS feature names. This would match a GNIS feature literally named "Gas Station" (unlikely) or partial matches. For category-based corridor search, the FTS5 query should use the `gnis_class` field when available, not free-text search against feature names. The `gnis_class` boosting at line 540-544 only reorders results; it doesn't change the query itself.
