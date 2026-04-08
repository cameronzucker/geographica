# Bug Hunt Report: Corridor Query Returns Too Few Results

## Scope

Deep analysis of the spatial search corridor pipeline, tracing the full path from user query through intent parsing, Nominatim/POI querying, to corridor filtering.

Files explored deeply:
- `services/search/spatial.py` — Intent parser, synonym table, corridor math, endpoint
- `services/search/main.py` — `_query_nominatim`, `_query_poi`, `_deduplicate`
- `scripts/build_poi_index.py` — POI database schema (GNIS-only, no commercial POIs)
- `frontend/app.js` — Route encoding, spatial search request construction

## Bugs

### 1. Synonym table normalizes to human text instead of OSM-searchable text
**Location:** `services/search/spatial.py:32` (synonym table) and `spatial.py:107` (`_lookup_category` return)
**Severity:** critical
**Evidence:**
The synonym table entry for gas stations is:
```python
{"synonyms": {"gas station", "fuel", "gas"}, "gnis_class": None, "fallback_text": "gas station"}
```
When ANY synonym matches (including "fuel"), `_lookup_category` returns `search_text = entry["fallback_text"]` = `"gas station"` (line 107). This text is sent directly to Nominatim as the `q` parameter (spatial.py line 529, main.py line 198).

OSM gas stations are tagged `amenity=fuel` and named "Circle K", "Shell", "Chevron" — not "gas station". Nominatim free-text search for "gas station" matches almost nothing. Even a user who correctly types "fuel" gets their query rewritten to "gas station" before it reaches Nominatim.

The synonym table needs a separate field for the Nominatim search term (e.g., `"nominatim_text": "fuel"` or `"osm_tags": ["amenity=fuel"]`) distinct from the human-readable `fallback_text`.

**Impact:** Corridor search for gas stations returns 1 result instead of ~12. This is the primary root cause of the reported bug.

### 2. Same text mismatch affects most commercial categories (not just gas stations)
**Location:** `services/search/spatial.py:30-58` (entire synonym table)
**Severity:** critical
**Evidence:**
The following categories have `gnis_class: None` (no GNIS fallback) and their `fallback_text` does NOT match OSM tagging conventions:

| Category | `fallback_text` sent to Nominatim | OSM tag | OSM names |
|---|---|---|---|
| Gas station | `"gas station"` | `amenity=fuel` | "Circle K", "Shell" |
| Campground | `"campground"` | `tourism=camp_site` | "KOA", "Joshua Tree" |
| Pharmacy | `"pharmacy"` | `amenity=pharmacy` | "CVS", "Walgreens" |
| Grocery | `"grocery"` | `shop=supermarket` | "Safeway", "Walmart" |
| Shelter | `"shelter"` | `amenity=shelter` | Various |
| Helipad | `"helipad"` | `aeroway=helipad` | Various |

Categories with `gnis_class` set (hospital, school, airport, summit, etc.) partially mitigate this because the GNIS FTS5 query can match on class name. But the Nominatim leg still underperforms for those too.

Categories like "restaurant" and "hotel" work somewhat because many OSM POIs have those words in their names, but results are still incomplete.

**Impact:** Most commercial/infrastructure corridor queries return far fewer results than exist in the data.

### 3. Candidate limit of 20 is far too low for corridor search over long routes
**Location:** `services/search/spatial.py:528`
**Severity:** significant
**Evidence:**
```python
limit = 20
nom_results, poi_results = await asyncio.gather(
    _query_nominatim(search_text, limit, bbox),
    _query_poi(search_text, limit, bbox),
```
For a 600 km route, the bbox covers a huge area (e.g., 6 degrees longitude x ~1 degree latitude for Phoenix-to-LA). Nominatim returns up to 20 results scattered across this entire bbox. The corridor filter then discards everything more than 2 km from the route. A route is a thin line through a wide bbox, so most of the 20 results will be far from the route.

To reliably get ~12 results within 2 km of a 600 km route, you'd need hundreds of candidates from the entire bbox area. The limit should scale with route length — e.g., `max(20, int(route_length_m / interval_m * 5))` or at minimum 50-100 for corridor queries.

The same limit=20 applies to the POI FTS5 query, which has the same problem for GNIS-backed categories.

**Impact:** Even if bug #1 were fixed, the hard limit of 20 candidates means long corridors would still produce sparse results.

### 4. GNIS database has no commercial POIs — search is structurally blind for road-trip categories
**Location:** `scripts/build_poi_index.py` (entire file) and `services/search/spatial.py:32-39`
**Severity:** significant
**Evidence:**
The POI database is built exclusively from GNIS (Geographic Names Information System), which contains geographic features: summits, springs, schools, hospitals, churches, dams, mines, etc. It does NOT contain commercial POIs like gas stations, restaurants, hotels, pharmacies, or grocery stores.

The synonym table's first 8 entries (lines 32-39) are all "Road trip / commercial" categories with `gnis_class: None`. For these categories, `_query_poi` returns 0 results because the GNIS FTS5 index has no matching features. The entire search depends solely on Nominatim for these categories.

**Impact:** Commercial corridor searches have only one data source (Nominatim), and that source is hampered by bug #1. There is no fallback.

### 5. Corridor bbox margin matches corridor width but doesn't account for Nominatim viewbox semantics
**Location:** `services/search/spatial.py:517`
**Severity:** minor
**Evidence:**
```python
margin = 0.02  # ~2.2 km
bbox = f"{min(lngs)-margin},{min(lats)-margin},{max(lngs)+margin},{max(lats)+margin}"
```
The 0.02-degree margin (~2.2 km) matches the 2 km corridor width (`CORRIDOR_WIDTH_M = 2_000`). This is geometrically correct for the corridor filter's needs.

However, when this bbox is passed to `_query_nominatim` with `bounded=1` (main.py line 208), it means Nominatim ONLY returns results inside the tight route-hugging box. This is correct for corridors, but the margin is so tight that POIs at highway exits (which can be 1-3 km off the highway centerline) could be excluded from the Nominatim viewbox before the corridor filter even runs.

More practically: the margin should be slightly larger than the corridor width to avoid boundary effects. A margin of 0.05 (~5.5 km) would be safer without significantly expanding the search area.

**Impact:** Edge cases where POIs near the corridor boundary are excluded by the Nominatim viewbox before precise distance calculation.

### 6. `point_to_segment_distance` bbox pre-check margin is too tight for long diagonal segments
**Location:** `services/search/spatial.py:351-355`
**Severity:** minor
**Evidence:**
```python
lat_min = min(a_lat, b_lat) - 0.02  # ~2.2 km margin
lat_max = max(a_lat, b_lat) + 0.02
lng_min = min(a_lng, b_lng) - 0.025
lng_max = max(a_lng, b_lng) + 0.025
if p_lat < lat_min or p_lat > lat_max or p_lng < lng_min or p_lng > lng_max:
    return float("inf")
```
After Douglas-Peucker simplification with 50m tolerance, segments through open desert can be very long (50+ km). For a long diagonal segment, a point 2 km from the segment's midpoint could be within the corridor but fail the bbox pre-check.

Consider a simplified segment from A(-114.0, 33.0) to B(-113.0, 34.0) — a ~130 km diagonal. The bbox is (-114.025, 32.98) to (-112.975, 34.02). A point at (-113.5, 33.52) that is 1.5 km perpendicular from the segment midpoint would pass the bbox check. But a point at (-113.52, 33.48) — still within 2 km of the segment — could pass too because it's well within the lat/lng bounds. For diagonal segments the bbox is wide enough along the diagonal.

However, the margins (0.02 lat, 0.025 lng) correspond to ~2.2 km. The corridor width is exactly 2 km. A point at exactly 1.99 km from the segment, at the extreme corner of the bbox, could fail the pre-check by a few meters. This is an edge case that would silently drop valid corridor results.

**Impact:** Occasional false negatives at corridor boundaries near segment bounding box corners. In practice this rarely affects results, but it violates the principle that the pre-check should never reject valid candidates.

## Design Concerns

### Synonym table conflates display text with search text
The `fallback_text` field serves dual duty: it's both the human-readable category name shown in the UI AND the search text sent to Nominatim. These need to be separate. OSM search requires different terms than what users say or what the UI displays.

### No Nominatim category/amenity filtering
Nominatim supports structured search parameters like `amenity=fuel` or `type=fuel` that would bypass the free-text mismatch entirely. The current implementation only uses free-text `q` parameter. Adding `amenity` or `osm_tag` parameters to the synonym table and using Nominatim's structured search would dramatically improve result quality.

### Single fixed limit regardless of search geometry
A 1 km radius proximity search and a 600 km corridor search both use `limit=20`. The corridor's search area is ~1000x larger, so it needs proportionally more candidates. The limit should be dynamic based on the search geometry.

### No pagination or iterative search strategy
For long corridors, an effective strategy would be to break the route into segments and query Nominatim separately for each segment with its own viewbox, then merge results. This would avoid the single-query limit bottleneck and improve geographic distribution of results.
