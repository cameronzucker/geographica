# City-Aware Spatial Search

**Date:** 2026-04-09
**Status:** Approved (revised after 5-round adversarial review: Opus, Haiku, Codex)
**Builds on:** 2026-04-08-natural-language-spatial-search-design.md

## Problem

The natural language spatial search parser does not understand queries that reference a city or place name. Queries like "gas stations in Flagstaff" or "restaurants in Phoenix along my route" are common real-world patterns — especially on road trips — but the current regex-based parser has no mechanism to:

1. Extract a place name from the query
2. Geocode that place name into a spatial constraint
3. Combine a city constraint with route corridor filtering

The parser currently recognizes three intent types (`plain`, `proximity`, `route_corridor`) triggered by keywords like "nearest", "near me", "along my route". The word "in" followed by a city name matches none of these patterns. The city name gets absorbed into `category_text`, which breaks synonym table lookup (e.g., `_lookup_category("gas station in flagstaff")` fails on exact match, then token-level match hits "gas" but loses "flagstaff" entirely).

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Place extraction | Find all ` in ` occurrences (space-bounded), use last valid one | `\b` word boundary is unreliable — `-` creates a boundary, so `\bin` matches inside "drive-in". Space-bounded matching is more predictable. |
| "in" disambiguation | Compound phrase table (normalized) + last-valid-"in" selection + geocode-as-arbiter | Case-insensitive. Scan all ` in ` positions, skip those whose left context is a protected compound phrase, use the last remaining one. This correctly handles "drive-in restaurants in phoenix". |
| Geocoding | Local Nominatim (already in stack) | Offline, ~100-200ms on localhost, no new dependencies |
| Geocode in parser vs endpoint | Endpoint (async) | Parser stays synchronous and fast; geocode is I/O |
| Geocode failure | Zero results + explicit UI error | Silent fallback to proximity would return misleading results from wrong location |
| Geocode timeout | 1 second hard timeout | Prevents blocking the entire search path if Nominatim is slow under memory pressure |
| Geocode caching | Async-safe dict cache keyed by `(place_name, bias_bucket)` | City names are highly repetitive on road trips. Key includes a coarse position bucket (rounded to 1 degree) so "mesa" near PHX and "mesa" near Denver cache separately. Use a dict with asyncio.Lock, not `functools.lru_cache` (which caches coroutine objects, not resolved values). |
| City + corridor bbox | Use city bbox alone for Nominatim POI queries; `corridor_filter()` does the real spatial constraint | Axis-aligned route bbox is too large for diagonal routes — intersecting it with city bbox doesn't meaningfully constrain. Let the existing corridor math handle it. |
| Ambiguous place names | Pass user position as Nominatim `viewbox` bias (not bounded) when available | "gas stations in mesa" resolves to nearest Mesa (AZ vs CO) relative to user |

## New Intent Types

Two new intents extend the existing three:

| Intent | Trigger | Example |
|--------|---------|---------|
| `city_proximity` | `"<category> in <place>"` (no route modifier) | "gas stations in flagstaff" |
| `city_corridor` | `"<category> in <place> along my route"` | "restaurants in phoenix along my route" |

### Fallback Chain (extended)

```
city_corridor (needs route + geocode)
  -> city_proximity (geocode ok, no route) [fallback_reason: "no_route"]
  -> zero results (geocode fails) [fallback_reason: "geocode_failed"]

city_proximity (needs geocode)
  -> zero results (geocode fails) [fallback_reason: "geocode_failed"]
```

Note: unlike the existing fallback chain which degrades to broader searches, city-intent geocode failures return zero results with an explicit error. This prevents the confusing UX of searching for "gas stations in las vegas" and silently getting results near the user's current location.

## Parser Changes

### New Regex

```python
# Protected compound phrases containing "in". Stored normalized (no hyphens, lowercase).
# These prevent the "in" within them from being treated as a place separator.
COMPOUND_IN_PHRASES = {"drive in", "check in", "walk in", "plug in", "built in",
                       "dine in", "sign in", "log in", "trade in", "break in"}
```

### Extraction Logic

Applied after corridor modifier stripping, before category lookup:

**Do NOT use `\b` word boundary for "in" detection.** Python's `\b` marks transitions between `\w` and `\W` characters. Since `-` is `\W`, `\bin` matches the "in" in "drive-in". Instead, use space-bounded splitting:

1. **Find all ` in ` positions** in the corridor-stripped query (case-insensitive, space on both sides). Also check for ` in` at end of string (space before, string end after).
2. **For each candidate position (right to left):** check if the text immediately before "in" (after normalizing hyphens to spaces) matches any `COMPOUND_IN_PHRASES` entry. If it does, skip this "in" — it's part of a compound.
3. **Use the last valid "in"** (rightmost non-compound "in") as the split point. This correctly handles "drive-in restaurants in phoenix" → last valid "in" is before "phoenix".
4. `before_in` = text before the split, `place_candidate` = text after the split.
5. **Sanitize `place_candidate`:** Strip trailing punctuation (commas, periods, exclamation marks) that may come from speech-to-text input.
6. Look up `before_in` (after filler word stripping) in synonym table:
   - **Category matches:** `category` = matched entry, `search_text` = entry's `fallback_text`, `place_name` = `place_candidate`
   - **Category doesn't match (Approach C):** `category` = None, `search_text` = `before_in` (raw), `place_name` = `place_candidate`. Geocode still attempted — handles "Shell in Tucson" where "Shell" is a brand, not a synonym table category.
7. **Empty `before_in`:** If `before_in` is empty after filler stripping (e.g., query was just "in flagstaff"), treat as `plain` intent with no place extraction. Rationale: "in flagstaff" alone is too ambiguous — the user likely meant to type more.
8. **No valid "in" found:** (all were compounds or none existed) → no place extraction, proceed with normal intent parsing.

### Updated Intent Dict (complete)

```python
{
    "intent": "city_proximity",          # plain | proximity | route_corridor | city_proximity | city_corridor
    "original_intent": "city_proximity", # same as intent before fallback
    "fallback_reason": None,             # no_position | no_route | geocode_failed | city_not_on_route | None
    "category": "gas station",           # synonym table match or None
    "gnis_class": None,                  # GNIS class or None
    "search_text": "gas station",        # text for Nominatim/FTS5 queries
    "nominatim_queries": ["fuel station", "gas", "Shell", "Chevron"],
    "osm_types": {("amenity", "fuel")},  # accepted OSM category/type pairs or None
    "osm_operator": None,                # BLM | USFS | NPS | None
    "radius_m": None,                    # explicit radius or None
    "interval_m": None,                  # corridor interval or None
    "place_name": "flagstaff",           # extracted place name or None (NEW)
}
```

### Intent Assignment

When `place_name` is present:

| Corridor modifier? | Route available? | Intent |
|--------------------|-----------------|--------|
| Yes | Yes | `city_corridor` |
| Yes | No | `city_proximity` (fallback_reason: "no_route") |
| No | — | `city_proximity` |

Note: `city_proximity` does NOT require GPS position — the geocoded city provides the spatial center. This differs from regular `proximity` which requires GPS.

## Endpoint Changes

### Geocoding Step

When `parsed["place_name"]` is not None:

1. Check LRU cache for `place_name` (case-normalized). If cached, use cached result.
2. Call local Nominatim: `GET /search?q={place_name}&limit=1&format=jsonv2` with **1-second timeout**.
   - If user position is available, add `viewbox={lon-2},{lat-2},{lon+2},{lat+2}&bounded=0` to bias results toward user's area (not bounded — just ranking bias). This resolves ambiguous names like "Mesa" to the nearest match.
3. On success: extract `lat`, `lon`, `boundingbox` from first result.
   - **Nominatim returns `boundingbox` as `[south_lat, north_lat, west_lon, east_lon]` (strings).** Parse accordingly: `lat_min=float(bb[0])`, `lat_max=float(bb[1])`, `lon_min=float(bb[2])`, `lon_max=float(bb[3])`. Pad by ~2km (0.02 degrees).
4. Cache the result (place_name → lat, lon, bbox).
5. On failure (empty response or timeout): return `{"results": [], "fallback_reason": "geocode_failed", "place_name": place_name, ...}`

### Bbox Construction

| Intent | Bbox |
|--------|------|
| `city_proximity` | Nominatim boundingbox for the city, padded ~2km |
| `city_corridor` | City bbox for Nominatim POI queries; `corridor_filter()` handles the route constraint |

For `city_corridor`: use the **city bbox alone** as the query bbox for Nominatim and OSM POI searches. Do NOT intersect with the route corridor bbox — an axis-aligned route bbox is too large for diagonal routes and the intersection is geometrically meaningless. Instead, let the existing `corridor_filter()` function do the real spatial constraint after results are fetched. This means: fetch POIs in the city, then filter to those within the corridor width of the route.

**City not on route detection:** After corridor filtering, if zero results survive (all POIs in the city were outside the corridor), return `fallback_reason: "city_not_on_route"`. This is more accurate than bbox intersection math.

### New `geocode_place()` Function

Do NOT reuse `_query_nominatim()` for geocoding. That function does bounded POI search with `bounded=1`. Geocoding needs a separate function:

```python
async def geocode_place(place_name: str, bias_lat: float = None, bias_lon: float = None) -> dict | None:
    """Geocode a place name via local Nominatim. Returns {lat, lon, bbox} or None.
    
    Uses async-safe dict cache (see caching section above). Do NOT use @lru_cache.
    """
    params = {"q": place_name, "limit": 1, "format": "jsonv2"}
    if bias_lat is not None and bias_lon is not None:
        # Bias (not bound) toward user's area — 2 degree box
        params["viewbox"] = f"{bias_lon-2},{bias_lat+2},{bias_lon+2},{bias_lat-2}"
        # Do NOT set bounded=1 — we want ranking bias, not hard filtering
    try:
        resp = await state.http_client.get(
            f"{NOMINATIM_URL}/search", params=params, timeout=1.0
        )
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        item = data[0]
        bb = item["boundingbox"]  # [south_lat, north_lat, west_lon, east_lon] as strings
        return {
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "bbox": f"{float(bb[2])},{float(bb[0])},{float(bb[3])},{float(bb[1])}",  # convert to lon_min,lat_min,lon_max,lat_max
        }
    except Exception:
        return None
```

**Async-safe caching:** Do NOT use `functools.lru_cache` on async functions — it caches coroutine objects, not resolved values, and repeated awaits will fail. Instead, implement a simple dict cache behind an `asyncio.Lock`:

```python
_geocode_cache: dict[tuple[str, int, int], dict | None] = {}
_geocode_lock = asyncio.Lock()

async def geocode_place(place_name: str, bias_lat: float = None, bias_lon: float = None) -> dict | None:
    # Cache key includes coarse position bucket (1-degree grid) so "mesa" near PHX
    # and "mesa" near Denver resolve to different entries.
    bias_bucket = (round(bias_lat or 0), round(bias_lon or 0))
    cache_key = (place_name.lower().strip(), bias_bucket[0], bias_bucket[1])
    
    async with _geocode_lock:
        if cache_key in _geocode_cache:
            return _geocode_cache[cache_key]
    
    # ... perform Nominatim call ...
    result = ...  # dict or None
    
    async with _geocode_lock:
        _geocode_cache[cache_key] = result
    return result
```

**Bbox format conversion:** Nominatim returns `boundingbox` as `[south_lat, north_lat, west_lon, east_lon]` (strings). The internal bbox format used by `_query_nominatim()` and `_query_poi()` is `"lon_min,lat_min,lon_max,lat_max"` (string). The conversion is:

```python
bb = item["boundingbox"]  # ["31.3", "31.5", "-112.1", "-111.9"]
bbox_internal = f"{float(bb[2])},{float(bb[0])},{float(bb[3])},{float(bb[1])}"
```

Parse to floats immediately and convert to the internal format. Do NOT pass raw Nominatim bbox strings through — the axis order is different and a pass-through will silently swap lat/lon.

**Geocode error handling:** The geocode helper must distinguish between "place not found" (empty Nominatim response) and "Nominatim unavailable" (timeout/network error). Both map to `fallback_reason: "geocode_failed"` for the user, but logging should differentiate them for debugging. Return `None` for both cases; the endpoint checks for `None` and returns zero results with the error.

### Query Execution

After the geocode, the query pipeline runs with the city bbox. **City intents use distinct execution paths**, not the existing proximity/corridor paths:

**Important:** The existing endpoint has multiple `if intent == "route_corridor"` and `if intent == "proximity"` branches for bbox creation, route segmentation, limit scaling, corridor filtering, and distance calculation. The new city intents MUST NOT be handled by adding more `elif` checks to these same branches. Instead, city intents should have their own execution path as described below. If the implementer finds the branching getting unwieldy, refactor around intent capabilities (e.g., `needs_corridor_filter`, `needs_city_bbox`) rather than string equality.

**`city_proximity` path:**
1. Use city bbox (from geocode) for all backend queries
2. Run multi-term Nominatim fan-out + GNIS + OSM POI (same as existing)
3. Deduplication + OSM type post-filtering (same as existing)
4. **Distance calculation:** compute `distance_m` from the *geocoded city center* (not GPS position). This differs from regular `proximity` which uses GPS.
5. Sort results by distance from city center
6. No radius filter — return all results within the city bbox

**`city_corridor` path:**
1. Use city bbox (from geocode) for all backend queries
2. Run multi-term Nominatim fan-out + GNIS + OSM POI (same as existing)
3. Deduplication + OSM type post-filtering (same as existing)
4. Apply `corridor_filter()` with the route polyline
5. If zero results survive corridor filtering: set `fallback_reason: "city_not_on_route"`
6. Results include both `distance_along_route_m` (from corridor_filter) and `distance_m` (from city center)

## Response Changes

New fields in the spatial search response:

```json
{
    "results": [...],
    "intent": "city_corridor",
    "original_intent": "city_corridor",
    "fallback_reason": null,
    "category": "gas station",
    "place_name": "flagstaff"
}
```

`place_name` is always included when extracted (even on failure, so frontend can display it in the error message).

## Frontend Changes

### Subtitle Display

New cases in the results subtitle logic (`app.js`):

| Condition | Subtitle |
|-----------|----------|
| `intent === "city_proximity"` | `"{Category} in {place_name}"` |
| `intent === "city_corridor"` | `"{Category} in {place_name} along route"` |
| `fallback_reason === "geocode_failed"` | `"Couldn't find '{place_name}' — check spelling?"` |
| `fallback_reason === "city_not_on_route"` | `"'{place_name}' doesn't appear to be along your route"` |

No other frontend changes. Pins, distance badges, map fitting, and result list rendering work as-is.

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| `"gas stations in"` (no place after "in") | Regex requires `.+` after "in" — no match, treated as plain/proximity |
| `"in flagstaff"` (nothing before "in") | `before_in` empty after filler strip → treated as plain intent, no place extraction (too ambiguous) |
| `"drive-in restaurants in phoenix"` | All ` in ` positions found. First "in" (after "drive-") → left context "drive" matches compound "drive in" (normalized). Skipped. Second "in" (before "phoenix") → no compound match. Last valid "in" → `before_in: "drive-in restaurants"`, `place: "phoenix"` |
| `"drive in restaurants in phoenix"` (no hyphen) | Same logic — first "in" left context "drive" matches compound. Second "in" used. Same result. |
| `"gas stations in 85001"` | Nominatim geocodes zip codes — works as-is |
| `"gas stations in mesa, az"` | Comma+state captured in place_name, Nominatim handles it |
| `"gas stations in mesa"` (ambiguous) | Nominatim `viewbox` bias from user position resolves to nearest Mesa. Without position, Nominatim's default ranking applies (larger city wins) |
| `"shell in tucson"` | Category lookup fails on "shell", Approach C: `search_text: "shell"`, `place_name: "tucson"` → geocode tucson, search "shell" in tucson bbox |
| `"gas stations in los vegas"` (typo) | Geocode fails → zero results, error: "Couldn't find 'los vegas' — check spelling?" |
| `"gas stations in phoenix!"` (punctuation) | Trailing punctuation stripped from place_candidate → `place_name: "phoenix"` |
| `"gas stations near flagstaff"` | Triggers existing proximity intent (not city-aware). "near" is handled by `RE_NEAR_ME`/etc., city context is lost. Out of scope — "near" + city is a future enhancement. |

## Performance

- Geocode call: ~100-200ms to local Nominatim (single result, simple query). 1-second hard timeout.
- LRU cache (maxsize=128) eliminates repeated geocode calls for the same city name. On road trips, users typically search 2-5 distinct cities — cache hit rate will be high after first query.
- Geocode runs before POI queries (determines bbox), adding ~100-200ms serial latency on cache miss. Total search time: ~400-1000ms (up from ~300-800ms), acceptable for the feature.
- On cache hit: no additional latency — geocode result is immediate.
- No additional database queries or indexes required.

## Testing

### Unit Tests (no network)

Intent parser tests in `test_intent_parser.py`:
- "in" extraction for known categories (gas stations, restaurants, etc.)
- Multi-word cities ("las vegas", "salt lake city")
- City with state suffix ("phoenix, az")
- Compound blocklist with single "in" ("drive-in theater" → no place extraction, `place_name: None`)
- **Compound blocklist with two "in"s:** "drive-in restaurants in phoenix" → `category: "restaurant"`, `place_name: "phoenix"`. Same for unhyphenated "drive in restaurants in phoenix".
- **"in" inside words:** "drinking water in phoenix" → `before_in: "drinking water"`, `place_name: "phoenix"` (the "in" inside "drinking" is not space-bounded, so it's not a split candidate)
- Approach C fallback ("shell in tucson" → `search_text: "shell"`, `place_name: "tucson"`)
- Corridor + city combo ("gas stations in flagstaff along my route")
- Fallback when no route available
- Empty before/after "in" edge cases
- **Regression: existing intents assert `place_name is None`.** Add `assert result["place_name"] is None` to at least one test per existing intent class (plain, proximity, corridor, fallback) to catch accidental place extraction.
- Trailing punctuation stripping ("gas stations in phoenix!" → `place_name: "phoenix"`)

### Integration Tests (require local Nominatim container)

Endpoint tests in `test_spatial_endpoint.py`:
- Container health check at session setup — fail immediately if Nominatim not responding
- **Geocode cache fixture:** clear the geocode cache before each test to prevent cross-test leakage
- "gas stations in flagstaff" → results near Flagstaff (~35.2N, -111.65W), intent `city_proximity`
- "gas stations in flagstaff along my route" with PHX→Flagstaff route → results within corridor near Flagstaff, intent `city_corridor`
- **City not on route:** "gas stations in los angeles along my route" with PHX→Flagstaff route → zero results, `fallback_reason: "city_not_on_route"`
- "gas stations in xyzzy_nonexistent" → zero results, `fallback_reason: "geocode_failed"`
- **Approach C endpoint test:** "shell in tucson" → non-empty results near Tucson, verifying that `search_text="shell"` is actually used for POI queries when category is None
- **Geocode timeout test:** monkeypatch the HTTP client to raise `TimeoutError` for the geocode call → verify `fallback_reason: "geocode_failed"` (this one test uses a mock — acceptable since we can't make real Nominatim slow on demand)
- Verify `place_name` in response for all city-intent queries
- Verify `distance_m` is computed from geocoded city center (not GPS) for `city_proximity`
- Verify bbox is geographically reasonable (results within expected lat/lon ranges)
