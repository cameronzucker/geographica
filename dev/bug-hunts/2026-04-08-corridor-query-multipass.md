# Bug Hunt Report: Corridor Query Returns Too Few Results

## Scope
**Files analyzed:** `services/search/spatial.py`, `services/search/main.py`, `scripts/build_poi_index.py`
**Passes performed:** 1 (Contract Violations), 2 (Cross-Sibling Patterns), 3 (Failure Modes), 4 (Concurrency), 5 (Error Propagation)
**Trigger:** "gas stations every 50 miles along my route" between Phoenix and Long Beach returned only 1 result on a ~600 km route.

---

## Bugs

### 1. Nominatim `bounded=1` with free-text `q` returns near-zero results for commercial categories
**Location:** `main.py:197-208`
**Severity:** critical
**Evidence:** The `_query_nominatim` function sends `q="gas station"` with `bounded=1` and a `viewbox` matching the route bbox. Nominatim's free-text `q` parameter performs geocoding (place-name lookup), NOT category/amenity search. Searching `q=gas station` asks Nominatim to find a *place literally named "gas station"*, not all POIs of type `amenity=fuel`. Nominatim's `/search` endpoint with `q=` returns named places, not amenity categories. The result: for `q="gas station"` Nominatim returns 0-2 results (only places that happen to have "gas station" in their name), not the hundreds of fuel stations along I-10.

The same problem affects every commercial category in the synonym table: "restaurant", "hotel", "campground", "pharmacy", "grocery", "fire station", "police station", "rest area", "shelter", "helipad". All have `gnis_class: None`, meaning the POI database cannot help either (GNIS is geographic features, not commercial POIs). These categories rely entirely on Nominatim, which returns near-zero results via free-text `q`.

To properly search for amenities, Nominatim requires **structured query parameters** or the **`/search?amenity=fuel`** form. The correct approach would be something like:
- `GET /search?amenity=fuel&viewbox=...&bounded=1&limit=50`
- Or use structured params: `street`, `city`, `county`, `state`, `country`, `postalcode` along with the special `amenity` parameter
- Or use Overpass API (not available offline without additional infrastructure)

**Impact:** Every commercial-category corridor search is fundamentally broken. "Gas stations along my route", "restaurants along my route", "hotels along my route" -- all return 0-2 results instead of dozens/hundreds. This is the root cause of the reported bug.
**Found in:** Pass 1 -- Contract Violations

---

### 2. Hard limit of 20 candidates is catastrophically low for corridor search
**Location:** `spatial.py:528-529`
**Severity:** critical
**Evidence:** The spatial search endpoint queries both Nominatim and POI with `limit = 20`. For a 600 km route corridor, the bbox is enormous (roughly Phoenix to Long Beach -- ~5 degrees of longitude). Even if Nominatim returned useful results, `limit=20` across a 600 km x 4 km rectangle means only 20 candidates to filter into a 2 km-wide corridor. Most of those 20 results will be far from the route centerline and get filtered out.

The corridor filter at `spatial.py:380-461` is well-implemented, but it can only work with candidates it receives. With 20 candidates spread across a massive bbox, the corridor filter will typically pass through 1-3 results (exactly matching the reported behavior of 1 result).

For corridor search, the limit should scale with route length. A 600 km route needs at minimum 200-500 candidates to have reasonable corridor coverage. The current code uses the same `limit=20` for all search types.

**Impact:** Even if Bug #1 were fixed, the hard limit of 20 ensures corridor searches on long routes return far too few results. A 600 km route at 50-mile intervals needs ~8 gas stations, but with only 20 candidates across a massive bbox, at most 1-3 will fall within the 2 km corridor.
**Found in:** Pass 1 -- Contract Violations

---

### 3. GNIS POI database contains zero commercial POIs -- no gas stations, restaurants, hotels, etc.
**Location:** `spatial.py:30-58` (synonym table), `scripts/build_poi_index.py:91-136`
**Severity:** critical
**Evidence:** The synonym table assigns `gnis_class: None` to all commercial categories (gas station, restaurant, hotel, campground, pharmacy, grocery, etc.). This is correct -- GNIS does not contain commercial POIs. GNIS is the Geographic Names Information System: it has summits, springs, schools, churches, airports, dams, bridges, and other geographic/civic features. It does NOT have gas stations, restaurants, hotels, or any commercial businesses.

The `_query_poi` function (main.py:238-297) does FTS5 search on the `poi_fts` table. For `search_text="gas station"`, FTS5 will match on the `name` column. But since no GNIS feature is named "gas station" (or contains those words), the FTS5 query returns 0 results.

This means for all commercial categories: Nominatim returns ~0 (Bug #1), GNIS returns 0 (no commercial data), corridor filter gets 0 candidates, user sees 0 results. The system has no data source for commercial POIs.

**Impact:** The entire commercial-category search capability is a dead end. The synonym table creates an illusion that gas stations, restaurants, etc. are searchable, but neither data source contains them.
**Found in:** Pass 2 -- Cross-Sibling Pattern Violations

---

### 4. Bbox margin of 0.02 degrees (~2.2 km) is too tight for corridor search
**Location:** `spatial.py:515-518`
**Severity:** significant
**Evidence:** When building the bbox for a route corridor query:
```python
margin = 0.02  # ~2.2 km
bbox = f"{min(lngs)-margin},{min(lats)-margin},{max(lngs)+margin},{max(lats)+margin}"
```
The margin is 0.02 degrees (~2.2 km), matching the corridor width. But this margin is applied to the route's bounding box, not to each point along the route. The bbox itself encompasses the entire route, so the margin only matters at the edges. This is actually fine for including edge-of-route results.

However, this tight bbox is passed to Nominatim with `bounded=1`, which hard-clips results to the viewbox. Combined with Bug #1 (free-text q), this further restricts the already-tiny result set.

**Impact:** Minor compared to Bugs #1-3, but the tight margin means any POI near the start/end of a route that's slightly outside the bbox gets excluded.
**Found in:** Pass 3 -- Failure Mode Reasoning

---

### 5. No fallback when corridor filter returns empty
**Location:** `spatial.py:563-564`
**Severity:** significant
**Evidence:** After the corridor filter runs:
```python
if intent == "route_corridor" and body.route:
    merged = corridor_filter(
        body.route, merged,
        corridor_width_m=CORRIDOR_WIDTH_M,
        interval_m=parsed.get("interval_m"),
    )
```
If `merged` is empty after filtering (which is the common case due to Bugs #1-3), the endpoint returns `{"results": [], ...}`. There is no fallback strategy: no widening of the corridor, no removal of `bounded=1`, no retry with higher limits, no message suggesting alternative searches.

The endpoint silently returns an empty list, and the user has no idea why a query like "gas stations every 50 miles along my route" on a major interstate returned nothing.

**Impact:** Users get silent failures with no diagnostic information. The `fallback_reason` field exists in the response but is only set for position/route availability, not for "search returned zero candidates" scenarios.
**Found in:** Pass 3 -- Failure Mode Reasoning

---

### 6. FTS5 phrase query for multi-word categories misses partial matches
**Location:** `main.py:248-249`
**Severity:** minor
**Evidence:** The POI FTS5 query wraps the search text in double quotes:
```python
safe_q = q.replace('"', '""')
fts_query = f'"{safe_q}"'
```
For `search_text = "gas station"`, this generates the FTS5 query `"gas station"` (phrase match). This requires the exact phrase "gas station" to appear consecutively in the indexed text. FTS5 phrase matching won't find a feature named "Gas N Go Station" or entries where "gas" and "station" appear in different indexed columns.

For the GNIS data this is mostly academic (no commercial POIs exist), but for geographic features it could miss results. For example, searching "ranger station" as a phrase won't match a GNIS feature with name="Ranger" and class="Station" because the FTS5 phrase search requires consecutive terms in a single column.

However, the FTS5 table indexes `name, class, state, county` -- so a phrase query searches across the virtual row. In FTS5, `"ranger station"` actually can match across columns if they're adjacent in the token stream. This is an FTS5 implementation detail that may or may not help depending on how the content table maps to the FTS.

**Impact:** Some valid GNIS matches may be missed due to phrase-only matching, but this is secondary to the fundamental data source gap.
**Found in:** Pass 4 -- Concurrency Reasoning (repurposed for query construction analysis)

---

### 7. Nominatim exceptions are silently swallowed with no logging
**Location:** `main.py:213-215`
**Severity:** significant
**Evidence:**
```python
try:
    resp = await state.http_client.get(f"{NOMINATIM_URL}/search", params=params)
    resp.raise_for_status()
    data = resp.json()
except Exception:
    return []
```
Any Nominatim error -- connection refused, timeout, HTTP 400 (bad request due to malformed params), HTTP 500 -- is caught by a bare `except Exception` and silently returns an empty list. No logging, no error context, no way to diagnose why searches fail.

Similarly in `spatial.py:534-535`:
```python
if isinstance(nom_results, BaseException):
    nom_results = []
```
Exceptions from the gather are silently converted to empty lists.

**Impact:** When Nominatim is down, misconfigured, or returning errors for certain query patterns, the user sees zero results with no indication of why. This makes debugging the corridor search problem much harder -- you can't tell if Nominatim returned 0 results legitimately or if it errored out.
**Found in:** Pass 5 -- Error Propagation

---

### 8. POI FTS5 query exceptions are silently swallowed
**Location:** `main.py:274-276`
**Severity:** minor
**Evidence:**
```python
try:
    async with state.poi_db.execute(sql, params) as cur:
        rows = await cur.fetchall()
except Exception:
    return []
```
Same pattern as Bug #7. FTS5 syntax errors (e.g., if user input creates malformed FTS5 queries despite the quoting), database lock issues, or I/O errors are all silently swallowed.

**Impact:** Silent failure mode makes debugging difficult. Lower severity because the POI database is simpler and less likely to fail than a network service.
**Found in:** Pass 5 -- Error Propagation

---

## Design Concerns

### The corridor search architecture has a fundamental data pipeline gap

The corridor search feature is well-engineered from an algorithmic perspective: the intent parser correctly identifies corridor queries, Douglas-Peucker simplification is reasonable, the corridor filter with interval selection is well-implemented. But the entire feature is built on two data sources that cannot serve its primary use cases:

1. **Nominatim** (via OSM data) theoretically has commercial POIs, but the free-text `q` parameter doesn't search them as amenities. Nominatim's geocoding API is designed for "find the place named X", not "find all places of category X within this area."

2. **GNIS** has geographic features but no commercial POIs. The synonym table correctly marks commercial categories with `gnis_class: None`.

The result is a well-built corridor filter that never receives candidates to filter. The fix requires either:
- Using Nominatim's structured search with the `amenity` parameter (e.g., `?amenity=fuel&viewbox=...`)
- Or chunking long corridors into smaller bbox segments, each querying with higher limits
- Or integrating an additional data source like a local Overpass/OSM extract for amenity queries
- Or pre-extracting OSM amenity data into the POI SQLite database alongside GNIS features

### The hard limit of 20 creates a silent quality cliff

The `limit=20` is fine for proximity searches (small bbox, nearby results) but catastrophically wrong for corridor searches (massive bbox, sparse hits within a narrow strip). The limit should be parameterized by search type, with corridor searches using limits proportional to route length (e.g., `min(500, route_length_km * 2)`).

### Silent error handling prevents operational diagnosis

Both `_query_nominatim` and `_query_poi` swallow all exceptions. For an offline-first system where services may be unavailable, this is a reasonable default -- but there should be at least `logging.warning()` calls so operators can diagnose issues via `docker compose logs search`. The response should include a `warnings` or `source_errors` field indicating which backends failed.
