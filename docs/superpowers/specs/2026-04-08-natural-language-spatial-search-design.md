# Natural Language Spatial Search

**Date:** 2026-04-08
**Status:** Approved (revised after 5-round adversarial review)
**Phase:** 2a (text input — precursor to Whisper STT in Phase 2b)

## Problem

Users want to type natural language spatial queries like "nearest gas station", "hospitals near me", or "find rest areas along my route" into the search box and get distance-ranked, context-aware results. Currently, search treats every query as a place name lookup — there is no concept of proximity, corridor, or spatial intent.

This is the text-input half of the Phase 2 voice AI feature. When Whisper STT arrives on the Hailo 10H NPU, the transcribed text feeds directly into this same parser. Building the parser and spatial search now means Phase 2b (voice) only needs to add the audio→text pipeline.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Parser type | Rule-based regex | Deterministic, <1ms, works offline, fails gracefully to plain search |
| Where parsing runs | Backend (search service) | Keeps frontend thin, available to all API consumers |
| Route data transport | Full decoded polyline from frontend | 5-20 KB per request, avoids Valhalla round-trip |
| Category matching | Hardcoded synonym table + raw text fallback | Reliable for common types, long tail handled by fallback |
| Result presentation | Distance badges + numbered map pins for ALL searches | Pins benefit even plain searches (multiple Filibertos problem) |
| Corridor algorithm | Douglas-Peucker + per-segment bbox pre-check | <500ms on Pi 5 (revised from <200ms after benchmarking) |
| Primary POI data source | Nominatim free-text (not GNIS for commercial POIs) | GNIS contains geographic features only, not businesses/amenities |

## Critical Design Notes (from adversarial review)

### GNIS database contains NO commercial POIs

The 304K-feature GNIS database contains geographic features: streams (68K), valleys (43K), summits (32K), reservoirs (29K), springs (28K), etc. It does NOT contain gas stations, restaurants, hotels, hospitals, or any commercial amenities. Category-based spatial search for common use cases depends entirely on Nominatim free-text search.

GNIS IS useful for geographic/emergency categories: summits, springs, wells, trails, dams, mines, airports, parks, schools, churches. The synonym table is corrected to reflect this.

### Corridor search performance

Pure Python haversine-based corridor filtering on ~2000 candidates x ~300 segments takes ~2-10s on Pi 5, not <200ms. Mitigation: per-segment bounding box pre-check (cheap float comparisons before expensive trig) provides ~10x speedup, bringing worst case to <500ms. The implementation MUST use the bbox pre-check optimization.

## API

### `POST /search/spatial`

New endpoint. The existing `GET /search` is unchanged for backwards compatibility. `GET /search` is the stable API for third-party consumers (ATAK, etc.); `POST /search/spatial` is the frontend's enriched search path.

**Request body:**
```json
{
  "query": "gas stations along my route",
  "position": { "lat": 33.45, "lon": -112.07 },
  "route": [[-112.07, 33.45], [-111.95, 33.52], [-111.09, 34.05]]
}
```

| Field | Type | Required | Constraints | Description |
|-------|------|----------|-------------|-------------|
| `query` | string | yes | max 500 chars | Raw natural language text from search box |
| `position` | object | no | lat: -90..90, lon: -180..180 | Current GPS position `{lat, lon}`. Sent when GPS has a fix. |
| `route` | array | no | max 10,000 points | Decoded route polyline as `[[lng, lat], ...]` (GeoJSON convention, matches MapLibre/Valhalla decoder output). Sent when a route is active. |

**Response:**
```json
{
  "results": [
    {
      "name": "Circle K",
      "type": "address",
      "class": "amenity",
      "lat": 33.52,
      "lon": -111.89,
      "display_name": "Circle K, 1234 E Main St, Mesa, AZ",
      "distance_m": 4200,
      "distance_along_route_m": 28500
    }
  ],
  "intent": "route_corridor",
  "original_intent": "route_corridor",
  "fallback_reason": null,
  "category": "gas station"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `results` | array | Same shape as existing `/search` results, plus two new fields |
| `results[].distance_m` | number or null | Straight-line distance from GPS position in meters |
| `results[].distance_along_route_m` | number or null | Distance along route to nearest projection point in meters |
| `intent` | string | Effective intent after fallback: `plain`, `proximity`, or `route_corridor` |
| `original_intent` | string | Intent detected by parser before any fallback |
| `fallback_reason` | string or null | Why fallback occurred: `no_position`, `no_route`, or null if no fallback |
| `category` | string or null | Extracted POI category, or null for plain searches |

**Behavior by intent:**

- **`plain`**: Delegates to existing Nominatim + POI search. `distance_m` is populated if `position` was sent (for map pin distance display). `distance_along_route_m` is null.
- **`proximity`**: Searches by category via Nominatim free-text (primary) and GNIS FTS5 (supplementary for geographic features). Results sorted by `distance_m`. Optional radius filter if user specified ("within 10 miles"). Default max radius: 50 km. Returns "No results within 50 km" when exceeded.
- **`route_corridor`**: Searches by category within a 2 km corridor of the route polyline. Results sorted by `distance_along_route_m`. Optional interval filter ("every 50 miles").

**Fallback chain:** `route_corridor` → `proximity` (if no route) → `plain` (if no position). The `original_intent` and `fallback_reason` fields let the frontend show contextual hints.

## Intent Parser

Rule-based regex pattern matcher. Runs in the search service before any database queries.

### Pre-processing

Before pattern matching:
1. **Filler word stripping**: Remove common filler words that don't affect intent or category: `find`, `the`, `a`, `an`, `me`, `some`, `show`, `search`, `look for`, `where is`, `where are`, `get`, `list`. Applied after spatial keyword extraction, before synonym lookup.
2. **Normalization**: Lowercase the query. Strip leading/trailing whitespace.

### Pattern matching (evaluated in order, first match wins)

1. **Route corridor**: `/along\s+(my\s+)?route/i`, `/on\s+(my\s+)?route/i`, `/every\s+(\d+)\s+(miles?|km|kilometers?)/i`
   - Requires: `route` in request body (falls back to proximity if absent, falls back to plain if no position either)
   - Extracts: category (remaining text after spatial keywords and fillers removed), optional interval

2. **Proximity**: `/nearest\s+/i`, `/closest\s+/i`, `/near\s+me/i`, `/near\s+here/i`, `/nearby\s+/i`, `/within\s+(\d+)\s+(miles?|km|kilometers?|mi)/i`
   - Requires: `position` in request body (falls back to plain if absent)
   - Extracts: category, optional radius

3. **Implicit proximity**: If no spatial keyword matched, but `position` is available AND the entire query (after filler stripping) exactly matches a synonym table key — auto-promote to `proximity` intent. This handles bare category words like "gas", "hospital", "water" without requiring explicit spatial keywords.

4. **Plain**: Everything else. Pass through to existing search logic.

### Category extraction

After removing spatial keywords and filler words, the remaining text is the category. Example: "find the nearest gas station" → remove "nearest" → remove "find the" → "gas station" → synonym table lookup.

**Synonym lookup is token-based, not exact match.** The extracted text is tokenized (split on whitespace). The synonym table is checked for: (a) exact match on the full extracted text, (b) exact match after removing trailing 's' (plural normalization), (c) any single token matching a synonym key. First match wins. This handles "gas stations" → "gas station", "find gas" → "gas", and "the nearest gas station to go" → "gas station".

### Synonym table

Maps natural language terms to search parameters. **Nominatim is always queried with the fallback text as free-text `q`.** The GNIS class column is used to supplement Nominatim results with geographic features from the POI FTS5 database — it is NOT the primary data source for commercial amenities.

**Road trip / commercial (Nominatim primary):**

| Synonyms | GNIS class | Fallback text |
|----------|------------|---------------|
| gas station, fuel, gas | — | gas station |
| restaurant, food, eat, dining | — | restaurant |
| hotel, motel, lodging | — | hotel |
| hospital, ER, emergency room | Hospital | hospital |
| campground, camping, campsite | — | campground |
| rest area, rest stop | — | rest area |
| pharmacy, drugstore | — | pharmacy |
| grocery, supermarket | — | grocery |

**Geographic / emergency ops (GNIS supplementary):**

| Synonyms | GNIS class | Fallback text |
|----------|------------|---------------|
| water, drinking water | Spring; Well | water |
| trailhead, trail | Trail | trailhead |
| park | Park | park |
| school | School | school |
| church | Church | church |
| airport | Airport | airport |
| fire station | — | fire station |
| police, police station | — | police station |
| summit, peak, hilltop, mountain | Summit | summit |
| tower, radio tower, repeater, comm site | Tower | tower |
| shelter, evacuation center, evac | — | shelter |
| helipad, landing zone, LZ | — | helipad |
| dam | Dam | dam |
| mine, quarry | Mine | mine |
| spring, hot spring | Spring | spring |
| bridge | Bridge | bridge |
| ranger station, forest service | Locale | ranger station |

**Unrecognized categories** fall through as raw text to both Nominatim free-text search and POI FTS5. Example: "find Filibertos near me" → intent=proximity, category=null, search text="Filibertos" with distance ranking.

## Corridor Search Algorithm

### Input
- Route polyline: array of [lng, lat] pairs (500-5000 points typically, GeoJSON convention)
- Corridor width: 2 km default (configurable)
- Candidate POIs: pre-filtered by route bounding box + buffer

### Steps
1. **Simplify** the polyline using Douglas-Peucker algorithm (tolerance ~50m). Reduces to ~100-500 segments.
2. **Bbox pre-filter**: Compute bounding box of simplified polyline, expand by corridor width. Query Nominatim with bbox and category text. Query POI database with bbox for GNIS class matches. Merge and deduplicate.
3. **Per-segment bbox pre-check**: For each candidate, compute a rough bounding box check against each segment before expensive haversine math. This is a cheap float comparison that eliminates ~90% of segment checks.
4. **Corridor filter**: For candidates passing the bbox pre-check, compute exact distance to the segment using point-to-line-segment haversine math. Keep only candidates within corridor width.
5. **Distance-along-route**: For each passing candidate, find the projection point on the nearest segment. Sum segment lengths from route start to that projection point.
6. **Sort** by distance-along-route.
7. **Interval filter** (for "every N miles" queries): Walk along the route in N-mile intervals. At each interval, keep only the closest result. This ensures even spacing.

### Performance (revised after Pi 5 benchmarking)
- Douglas-Peucker on 5000 points: ~5ms
- Bbox pre-filter SQL: ~1-50ms depending on bbox size
- Per-segment bbox pre-check + corridor filter on ~2000 candidates: <500ms (bbox pre-check eliminates ~90% of haversine calls)
- Total: <500ms typical, <1s worst case (long cross-state routes)

### New utility functions
- `haversine_m()` — already exists at `services/search/main.py:122`
- `point_to_segment_distance()` — ~30 lines, haversine-based with bbox pre-check
- `douglas_peucker()` — ~25 lines, standard algorithm using haversine
- `distance_along_polyline()` — ~15 lines, cumulative segment sum

### Spatial index on POI database
Add lat/lon index to `poi_features` table: `CREATE INDEX IF NOT EXISTS idx_poi_latlon ON poi_features (lat, lon)`. Currently the table has no index on coordinates, causing full-table scans for bbox queries.

## Frontend Changes

### New state variable
Add `lastRouteCoords` (array of [lng, lat] pairs or null) to module state. Populated in `renderRoute()` when decoding the Valhalla polyline. Cleared in `clearRoute()`. This avoids re-decoding the polyline on every search request.

### Search input
- `performSearch()` switches from `GET /search/search` to `POST /search/spatial`
- Every request includes `position` (from `gpsLastPos`) and `route` (from `lastRouteCoords`) when available
- `geocodeForRoute()` (used by routing panel) continues to use the existing `GET /search` endpoint — it doesn't need spatial awareness
- **Graceful degradation**: If `POST /search/spatial` returns 404 or 405 (stale frontend hitting old backend), fall back to `GET /search` with just the query text

### Result rendering (ALL searches, not just spatial)
- Each result item shows a circled number (1, 2, 3...) matching the map pin
- Spatial results additionally show a distance badge: "2.3 mi" (proximity) or "in 47 mi" (corridor)
- Distance badges respect the imperial/metric unit toggle
- A subtitle line shows detected intent when spatial: "Nearest gas stations" or "Gas stations along route"
- **Fallback hints**: When `original_intent !== intent` (fallback occurred), show contextual message: "Enable GPS for proximity search" or "Set a route for corridor search"

### Map result pins (ALL searches)
- When search returns results, drop numbered markers on the map (amber/orange color, distinct from GPS blue and route purple)
- Markers show the result number (1, 2, 3...)
- Click a list item → fly to corresponding pin (with `padding` to avoid sidebar/results panel occlusion), open popup with result details
- Click a map pin → scroll to and highlight the corresponding list item (add `search-result-active` CSS class, use `scrollIntoView()`)
- Add `pointer` cursor on pin hover via `mouseenter`/`mouseleave` handlers (matching existing imported-feature layer pattern)
- Pins are cleared when: new search is performed, search results are dismissed, or user clicks "Clear results"
- **Implementation**: Register `search-results` source and symbol layer in `addPlaceholderSources()` (at end of layer stack, renders on top). This ensures survival across style swaps (Positron↔Dark Matter).
- **Remove old pattern**: The existing `searchMarker`/`searchPopup` single-DOM-marker approach in `selectSearchResult()` is replaced by the symbol layer pins. Remove the old marker creation code.

### When no results
- If spatial intent was detected but no position/route available, show hint based on `fallback_reason`
- If spatial intent was detected but zero results found, show: "No gas stations found within 50 km" or "No gas stations found within 2 km of your route"

## Files Changed

| File | Change |
|------|--------|
| `services/search/main.py` | New `POST /search/spatial` endpoint, intent parser, corridor search, category table, POI lat/lon index |
| `frontend/app.js` | Switch to POST, `lastRouteCoords` state, numbered pins for all results, distance badges, remove old `searchMarker` pattern |

Files **not** changed: `services/gps/main.py`, `nginx/nginx.conf` (POST proxies correctly already), `docker-compose.yml`, navigation engine, pipeline scripts.

## Known Limitations (explicit non-goals for Phase 2a)

- **"near [place name]"** (e.g., "water near Flagstaff") — not supported. The proximity regex only matches "near me"/"near here". Workaround: navigate to the area on the map, then search "nearest water". Candidate for future LLM fallback.
- **"along [road name]"** (e.g., "restaurants along Interstate 10") — not supported. Requires geocoding a road to a polyline. Workaround: set a route along that road first, then search "restaurants along my route".
- **"nearest X to [address]"** (e.g., "nearest gas station to 123 Main St") — not supported. Requires geocoding the address as a reference point. Candidate for future LLM fallback.
- **Whisper STT / voice input** (Phase 2b)
- **LLM-based intent parsing** (regex handles the known query space; clean interface for future LLM fallback layer)
- **Search typeahead / live-as-you-type** (remains Enter-to-submit)
- **Multi-pin interaction beyond fly-to and highlight** (no drag, no reorder, no "route to this result")

## Phase 2b Bridge

When Whisper STT arrives on the Hailo 10H NPU:
1. User presses a microphone button (or hardware PTT)
2. Audio is captured via Web Audio API, sent to a local Whisper endpoint
3. Whisper transcribes to text
4. Text is placed in the search input and submitted to `POST /search/spatial`
5. Results render identically to typed queries

The entire spatial search pipeline built here is reused unchanged. Phase 2b only adds the audio→text layer.
