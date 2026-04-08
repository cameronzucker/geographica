# Natural Language Spatial Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add natural language spatial search so users can type queries like "nearest gas station", "hospitals near me", or "gas stations along my route" and get distance-ranked, context-aware results with numbered map pins.

**Architecture:** A new `POST /search/spatial` endpoint in the search FastAPI service handles intent detection (rule-based regex), category extraction (synonym table + fallback), and spatial filtering (proximity radius or route corridor). The frontend sends GPS position and decoded route geometry alongside every query, renders numbered pins for all search results, and shows distance badges for spatial results.

**Tech Stack:** Python/FastAPI (backend), vanilla JS/MapLibre GL JS (frontend), SQLite FTS5 (POI), Nominatim (geocoding), aiosqlite, httpx

**Spec:** `docs/superpowers/specs/2026-04-08-natural-language-spatial-search-design.md`

---

## File Structure

### New files
- `services/search/spatial.py` — intent parser, synonym table, corridor math, spatial endpoint logic (~300 lines)
- `tests/test_intent_parser.py` — tests for intent detection and category extraction
- `tests/test_corridor.py` — tests for Douglas-Peucker, point-to-segment distance, corridor filtering
- `tests/test_spatial_endpoint.py` — integration tests for POST /search/spatial

### Modified files
- `services/search/main.py` — import and mount the spatial router, add POI lat/lon index on startup
- `frontend/app.js` — switch to POST, add `lastRouteCoords`, numbered pins, distance badges, remove old `searchMarker`

---

## Task 1: Intent Parser + Synonym Table

**Files:**
- Create: `services/search/spatial.py`
- Create: `tests/test_intent_parser.py`

This task builds the core parsing logic in isolation — no database, no HTTP, no corridor math yet.

- [ ] **Step 1: Write failing tests for intent detection**

```python
# tests/test_intent_parser.py
"""Tests for the natural language intent parser and category extraction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from spatial import parse_intent


class TestIntentDetection:
    def test_plain_query(self):
        result = parse_intent("Phoenix", has_position=True, has_route=False)
        assert result["intent"] == "plain"
        assert result["category"] is None

    def test_nearest_gas_station(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"
        assert result["search_text"] == "gas station"

    def test_near_me(self):
        result = parse_intent("hospitals near me", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "hospital"

    def test_along_my_route(self):
        result = parse_intent("gas stations along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "gas station"

    def test_every_n_miles(self):
        result = parse_intent("gas stations every 50 miles along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "gas station"
        assert result["interval_m"] is not None

    def test_within_radius(self):
        result = parse_intent("gas stations within 10 miles", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"
        assert result["radius_m"] is not None
        # 10 miles ~ 16093 meters
        assert abs(result["radius_m"] - 16093) < 100

    def test_corridor_fallback_to_proximity(self):
        """along my route without route data falls back to proximity."""
        result = parse_intent("gas stations along my route", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["original_intent"] == "route_corridor"
        assert result["fallback_reason"] == "no_route"

    def test_proximity_fallback_to_plain(self):
        """nearest X without position falls back to plain."""
        result = parse_intent("nearest hospital", has_position=False, has_route=False)
        assert result["intent"] == "plain"
        assert result["original_intent"] == "proximity"
        assert result["fallback_reason"] == "no_position"

    def test_route_66_near_me(self):
        """'Route 66' should not trigger corridor intent."""
        result = parse_intent("Route 66 near me", has_position=True, has_route=True)
        assert result["intent"] == "proximity"
        # Category should be the raw text "route 66", not matched in synonym table
        assert result["category"] is None
        assert "route 66" in result["search_text"].lower()

    def test_filibertos_near_me(self):
        """Unrecognized business name with spatial intent."""
        result = parse_intent("Filibertos near me", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] is None
        assert "filibertos" in result["search_text"].lower()

    def test_bare_category_with_position(self):
        """Bare category word auto-promotes to proximity when position available."""
        result = parse_intent("gas", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_bare_category_without_position(self):
        """Bare category word without position stays plain."""
        result = parse_intent("gas", has_position=False, has_route=False)
        assert result["intent"] == "plain"

    def test_plural_normalization(self):
        """Plurals should match singular synonym table entries."""
        result = parse_intent("nearest hospitals", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "hospital"

    def test_filler_words_stripped(self):
        """'find the nearest gas station' should extract 'gas station'."""
        result = parse_intent("find the nearest gas station", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_summit_gnis_category(self):
        """AREDN/emergency category should be recognized."""
        result = parse_intent("nearest summit", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "summit"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_intent_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spatial'`

- [ ] **Step 3: Implement the intent parser and synonym table**

```python
# services/search/spatial.py
"""Natural language spatial search — intent parser, synonym table, corridor math.

This module provides the core logic for POST /search/spatial.
"""
import math
import re
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MILES_TO_METERS = 1609.34
KM_TO_METERS = 1000.0
DEFAULT_PROXIMITY_RADIUS_M = 50_000  # 50 km
CORRIDOR_WIDTH_M = 2_000  # 2 km
EARTH_RADIUS_M = 6_371_000

FILLER_WORDS = {
    "find", "the", "a", "an", "me", "some", "show", "search",
    "look", "for", "where", "is", "are", "get", "list",
}

# ---------------------------------------------------------------------------
# Synonym table
# ---------------------------------------------------------------------------
# Each entry: { synonyms: set, gnis_class: str|None, fallback_text: str }
SYNONYM_TABLE = [
    {"synonyms": {"gas station", "fuel", "gas"}, "gnis_class": None, "fallback_text": "gas station"},
    {"synonyms": {"restaurant", "food", "eat", "dining"}, "gnis_class": None, "fallback_text": "restaurant"},
    {"synonyms": {"hotel", "motel", "lodging"}, "gnis_class": None, "fallback_text": "hotel"},
    {"synonyms": {"hospital", "er", "emergency room"}, "gnis_class": "Hospital", "fallback_text": "hospital"},
    {"synonyms": {"campground", "camping", "campsite"}, "gnis_class": None, "fallback_text": "campground"},
    {"synonyms": {"rest area", "rest stop"}, "gnis_class": None, "fallback_text": "rest area"},
    {"synonyms": {"pharmacy", "drugstore"}, "gnis_class": None, "fallback_text": "pharmacy"},
    {"synonyms": {"grocery", "supermarket"}, "gnis_class": None, "fallback_text": "grocery"},
    {"synonyms": {"water", "drinking water"}, "gnis_class": "Spring", "fallback_text": "water"},
    {"synonyms": {"trailhead", "trail"}, "gnis_class": "Trail", "fallback_text": "trailhead"},
    {"synonyms": {"park"}, "gnis_class": "Park", "fallback_text": "park"},
    {"synonyms": {"school"}, "gnis_class": "School", "fallback_text": "school"},
    {"synonyms": {"church"}, "gnis_class": "Church", "fallback_text": "church"},
    {"synonyms": {"airport"}, "gnis_class": "Airport", "fallback_text": "airport"},
    {"synonyms": {"fire station"}, "gnis_class": None, "fallback_text": "fire station"},
    {"synonyms": {"police", "police station"}, "gnis_class": None, "fallback_text": "police station"},
    {"synonyms": {"summit", "peak", "hilltop", "mountain"}, "gnis_class": "Summit", "fallback_text": "summit"},
    {"synonyms": {"tower", "radio tower", "repeater", "comm site"}, "gnis_class": "Tower", "fallback_text": "tower"},
    {"synonyms": {"shelter", "evacuation center", "evac"}, "gnis_class": None, "fallback_text": "shelter"},
    {"synonyms": {"helipad", "landing zone", "lz"}, "gnis_class": None, "fallback_text": "helipad"},
    {"synonyms": {"dam"}, "gnis_class": "Dam", "fallback_text": "dam"},
    {"synonyms": {"mine", "quarry"}, "gnis_class": "Mine", "fallback_text": "mine"},
    {"synonyms": {"spring", "hot spring"}, "gnis_class": "Spring", "fallback_text": "spring"},
    {"synonyms": {"bridge"}, "gnis_class": "Bridge", "fallback_text": "bridge"},
    {"synonyms": {"ranger station", "forest service"}, "gnis_class": "Locale", "fallback_text": "ranger station"},
]

# Build a flat lookup: normalized synonym text -> table entry
_SYNONYM_LOOKUP: dict[str, dict] = {}
for _entry in SYNONYM_TABLE:
    for _syn in _entry["synonyms"]:
        _SYNONYM_LOOKUP[_syn.lower()] = _entry

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
# Route corridor patterns (checked first)
RE_ALONG_ROUTE = re.compile(r'\balong\s+(my\s+)?route\b', re.IGNORECASE)
RE_ON_ROUTE = re.compile(r'\bon\s+(my\s+)?route\b', re.IGNORECASE)
RE_EVERY_N = re.compile(r'\bevery\s+(\d+)\s+(miles?|km|kilometers?)\b', re.IGNORECASE)

# Proximity patterns
RE_NEAREST = re.compile(r'\bnearest\s+', re.IGNORECASE)
RE_CLOSEST = re.compile(r'\bclosest\s+', re.IGNORECASE)
RE_NEAR_ME = re.compile(r'\bnear\s+me\b', re.IGNORECASE)
RE_NEAR_HERE = re.compile(r'\bnear\s+here\b', re.IGNORECASE)
RE_NEARBY = re.compile(r'\bnearby\s+', re.IGNORECASE)
RE_WITHIN = re.compile(r'\bwithin\s+(\d+)\s+(miles?|km|kilometers?|mi)\b', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------
def _strip_filler(text: str) -> str:
    """Remove common filler words from extracted category text."""
    tokens = text.split()
    return " ".join(t for t in tokens if t.lower() not in FILLER_WORDS)


def _lookup_category(text: str) -> tuple[Optional[dict], str]:
    """Look up category in synonym table. Returns (entry, search_text).

    Token-based matching with plural normalization:
    1. Try exact match on full text
    2. Try with trailing 's' stripped
    3. Try each token individually
    """
    normalized = text.strip().lower()
    if not normalized:
        return None, text

    # Exact match
    if normalized in _SYNONYM_LOOKUP:
        entry = _SYNONYM_LOOKUP[normalized]
        return entry, entry["fallback_text"]

    # Plural normalization (strip trailing 's')
    if normalized.endswith("s") and normalized[:-1] in _SYNONYM_LOOKUP:
        entry = _SYNONYM_LOOKUP[normalized[:-1]]
        return entry, entry["fallback_text"]

    # Multi-word: try the full phrase minus trailing 's'
    # e.g., "gas stations" -> "gas station"
    if normalized.endswith("s"):
        singular = normalized[:-1]
        if singular in _SYNONYM_LOOKUP:
            entry = _SYNONYM_LOOKUP[singular]
            return entry, entry["fallback_text"]

    # Token-level match: check if any single token matches
    tokens = normalized.split()
    for token in tokens:
        if token in _SYNONYM_LOOKUP:
            entry = _SYNONYM_LOOKUP[token]
            return entry, entry["fallback_text"]
        if token.endswith("s") and token[:-1] in _SYNONYM_LOOKUP:
            entry = _SYNONYM_LOOKUP[token[:-1]]
            return entry, entry["fallback_text"]

    # No match — return raw text as search text
    return None, text.strip()


def _parse_unit_to_meters(value: int, unit: str) -> float:
    """Convert a distance value + unit string to meters."""
    unit = unit.lower().rstrip("s")  # "miles" -> "mile"
    if unit in ("mile", "mi"):
        return value * MILES_TO_METERS
    return value * KM_TO_METERS


def parse_intent(
    query: str,
    has_position: bool = False,
    has_route: bool = False,
) -> dict:
    """Parse a natural language query into a structured intent.

    Returns dict with keys:
      intent: 'plain' | 'proximity' | 'route_corridor'
      original_intent: same as intent before fallback
      fallback_reason: 'no_position' | 'no_route' | None
      category: str or None (synonym table match)
      gnis_class: str or None
      search_text: str (raw text for Nominatim/FTS5)
      radius_m: float or None (for proximity with explicit radius)
      interval_m: float or None (for corridor with "every N miles")
    """
    text = query.strip()
    intent = "plain"
    original_intent = "plain"
    fallback_reason = None
    radius_m = None
    interval_m = None
    spatial_keywords_removed = text

    # --- Rule 1: Route corridor ---
    corridor_match = RE_ALONG_ROUTE.search(text) or RE_ON_ROUTE.search(text)
    every_match = RE_EVERY_N.search(text)

    if corridor_match or every_match:
        original_intent = "route_corridor"
        # Remove spatial keywords to extract category
        spatial_keywords_removed = text
        if corridor_match:
            spatial_keywords_removed = (
                spatial_keywords_removed[:corridor_match.start()]
                + spatial_keywords_removed[corridor_match.end():]
            )
        if every_match:
            interval_m = _parse_unit_to_meters(
                int(every_match.group(1)), every_match.group(2)
            )
            spatial_keywords_removed = (
                spatial_keywords_removed[:every_match.start()]
                + spatial_keywords_removed[every_match.end():]
            )

        if has_route:
            intent = "route_corridor"
        elif has_position:
            intent = "proximity"
            fallback_reason = "no_route"
        else:
            intent = "plain"
            fallback_reason = "no_position"

    # --- Rule 2: Proximity ---
    elif RE_NEAREST.search(text):
        original_intent = "proximity"
        spatial_keywords_removed = RE_NEAREST.sub("", text)
        intent = "proximity" if has_position else "plain"
        if not has_position:
            fallback_reason = "no_position"

    elif RE_CLOSEST.search(text):
        original_intent = "proximity"
        spatial_keywords_removed = RE_CLOSEST.sub("", text)
        intent = "proximity" if has_position else "plain"
        if not has_position:
            fallback_reason = "no_position"

    elif RE_NEAR_ME.search(text):
        original_intent = "proximity"
        spatial_keywords_removed = RE_NEAR_ME.sub("", text)
        intent = "proximity" if has_position else "plain"
        if not has_position:
            fallback_reason = "no_position"

    elif RE_NEAR_HERE.search(text):
        original_intent = "proximity"
        spatial_keywords_removed = RE_NEAR_HERE.sub("", text)
        intent = "proximity" if has_position else "plain"
        if not has_position:
            fallback_reason = "no_position"

    elif RE_NEARBY.search(text):
        original_intent = "proximity"
        spatial_keywords_removed = RE_NEARBY.sub("", text)
        intent = "proximity" if has_position else "plain"
        if not has_position:
            fallback_reason = "no_position"

    elif RE_WITHIN.search(text):
        original_intent = "proximity"
        m = RE_WITHIN.search(text)
        radius_m = _parse_unit_to_meters(int(m.group(1)), m.group(2))
        spatial_keywords_removed = RE_WITHIN.sub("", text)
        intent = "proximity" if has_position else "plain"
        if not has_position:
            fallback_reason = "no_position"

    # Strip filler words from extracted category text
    category_text = _strip_filler(spatial_keywords_removed).strip()

    # Look up category in synonym table
    entry, search_text = _lookup_category(category_text)

    # --- Rule 3: Implicit proximity for bare category words ---
    if intent == "plain" and fallback_reason is None and has_position and entry is not None:
        intent = "proximity"
        original_intent = "proximity"

    return {
        "intent": intent,
        "original_intent": original_intent,
        "fallback_reason": fallback_reason,
        "category": entry["fallback_text"] if entry else None,
        "gnis_class": entry["gnis_class"] if entry else None,
        "search_text": search_text,
        "radius_m": radius_m,
        "interval_m": interval_m,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_intent_parser.py -v`
Expected: All 16 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/search/spatial.py tests/test_intent_parser.py
git commit -m "feat: intent parser with synonym table and category extraction"
```

---

## Task 2: Corridor Math Utilities

**Files:**
- Modify: `services/search/spatial.py` (add corridor functions)
- Create: `tests/test_corridor.py`

- [ ] **Step 1: Write failing tests for corridor math**

```python
# tests/test_corridor.py
"""Tests for corridor search math: Douglas-Peucker, point-to-segment, corridor filter."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from spatial import (
    haversine_m,
    douglas_peucker,
    point_to_segment_distance,
    corridor_filter,
    distance_along_polyline,
)


class TestHaversine:
    def test_same_point(self):
        assert haversine_m(33.45, -112.07, 33.45, -112.07) == 0.0

    def test_known_distance(self):
        # Phoenix to Tucson: ~180 km
        d = haversine_m(33.45, -112.07, 32.22, -110.97)
        assert 170_000 < d < 190_000


class TestDouglasPeucker:
    def test_straight_line_simplified(self):
        # 5 colinear points should reduce to 2
        pts = [[-112.0, 33.0], [-111.5, 33.0], [-111.0, 33.0],
               [-110.5, 33.0], [-110.0, 33.0]]
        result = douglas_peucker(pts, tolerance_m=100)
        assert len(result) == 2
        assert result[0] == pts[0]
        assert result[-1] == pts[-1]

    def test_zigzag_preserved(self):
        # Points with large deviations should be preserved
        pts = [[-112.0, 33.0], [-111.5, 34.0], [-111.0, 33.0],
               [-110.5, 34.0], [-110.0, 33.0]]
        result = douglas_peucker(pts, tolerance_m=100)
        assert len(result) == 5  # All preserved due to large deviations

    def test_empty_and_short(self):
        assert douglas_peucker([], tolerance_m=100) == []
        assert douglas_peucker([[-112.0, 33.0]], tolerance_m=100) == [[-112.0, 33.0]]
        pts = [[-112.0, 33.0], [-111.0, 33.0]]
        assert douglas_peucker(pts, tolerance_m=100) == pts


class TestPointToSegment:
    def test_point_on_segment(self):
        # Midpoint of a segment should be distance ~0
        d = point_to_segment_distance(
            33.0, -111.5,  # point (midpoint-ish)
            [-112.0, 33.0], [-111.0, 33.0]  # segment [lng, lat]
        )
        assert d < 100  # within 100m of the line

    def test_point_far_from_segment(self):
        d = point_to_segment_distance(
            35.0, -111.5,  # point 2 degrees north
            [-112.0, 33.0], [-111.0, 33.0]
        )
        assert d > 200_000  # > 200 km


class TestCorridorFilter:
    def test_basic_corridor(self):
        route = [[-112.07, 33.45], [-111.0, 33.45], [-110.0, 33.45]]
        candidates = [
            {"lat": 33.45, "lon": -111.5, "name": "On route"},
            {"lat": 35.0, "lon": -111.5, "name": "Far away"},
            {"lat": 33.46, "lon": -111.5, "name": "Just off route"},
        ]
        results = corridor_filter(route, candidates, corridor_width_m=2000)
        names = [r["name"] for r in results]
        assert "On route" in names
        assert "Just off route" in names
        assert "Far away" not in names

    def test_distance_along_route(self):
        route = [[-112.0, 33.0], [-111.0, 33.0], [-110.0, 33.0]]
        candidates = [
            {"lat": 33.0, "lon": -111.0, "name": "Midpoint"},
            {"lat": 33.0, "lon": -110.5, "name": "Three-quarter"},
        ]
        results = corridor_filter(route, candidates, corridor_width_m=5000)
        # Results should be sorted by distance_along_route_m
        assert len(results) == 2
        assert results[0]["name"] == "Midpoint"
        assert results[1]["name"] == "Three-quarter"
        assert results[0]["distance_along_route_m"] < results[1]["distance_along_route_m"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_corridor.py -v`
Expected: FAIL with `ImportError: cannot import name 'haversine_m' from 'spatial'`

- [ ] **Step 3: Implement corridor math in spatial.py**

Add the following functions to `services/search/spatial.py`:

```python
# ---------------------------------------------------------------------------
# Haversine (duplicated from main.py for module independence)
# ---------------------------------------------------------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in metres between two lat/lon points."""
    rlat1, rlon1, rlat2, rlon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Douglas-Peucker polyline simplification
# ---------------------------------------------------------------------------
def _point_line_distance_m(
    plng: float, plat: float,
    a_lng: float, a_lat: float,
    b_lng: float, b_lat: float,
) -> float:
    """Approximate perpendicular distance from point to line segment AB in meters.

    Uses cross-track distance formula for short segments.
    """
    d_ap = haversine_m(plat, plng, a_lat, a_lng)
    d_ab = haversine_m(a_lat, a_lng, b_lat, b_lng)
    if d_ab < 1.0:
        return d_ap
    # Bearing from A to P and A to B
    bear_ap = math.atan2(
        math.sin(math.radians(plng - a_lng)) * math.cos(math.radians(plat)),
        math.cos(math.radians(a_lat)) * math.sin(math.radians(plat))
        - math.sin(math.radians(a_lat)) * math.cos(math.radians(plat))
        * math.cos(math.radians(plng - a_lng))
    )
    bear_ab = math.atan2(
        math.sin(math.radians(b_lng - a_lng)) * math.cos(math.radians(b_lat)),
        math.cos(math.radians(a_lat)) * math.sin(math.radians(b_lat))
        - math.sin(math.radians(a_lat)) * math.cos(math.radians(b_lat))
        * math.cos(math.radians(b_lng - a_lng))
    )
    cross_track = abs(math.asin(
        math.sin(d_ap / EARTH_RADIUS_M) * math.sin(bear_ap - bear_ab)
    )) * EARTH_RADIUS_M
    return cross_track


def douglas_peucker(points: list[list[float]], tolerance_m: float = 50.0) -> list[list[float]]:
    """Simplify a [lng, lat] polyline using Douglas-Peucker algorithm."""
    if len(points) <= 2:
        return list(points)

    # Find point with max distance from the line between first and last
    max_dist = 0.0
    max_idx = 0
    a_lng, a_lat = points[0]
    b_lng, b_lat = points[-1]

    for i in range(1, len(points) - 1):
        d = _point_line_distance_m(points[i][0], points[i][1], a_lng, a_lat, b_lng, b_lat)
        if d > max_dist:
            max_dist = d
            max_idx = i

    if max_dist > tolerance_m:
        left = douglas_peucker(points[:max_idx + 1], tolerance_m)
        right = douglas_peucker(points[max_idx:], tolerance_m)
        return left[:-1] + right
    else:
        return [points[0], points[-1]]


# ---------------------------------------------------------------------------
# Point-to-segment distance with bbox pre-check
# ---------------------------------------------------------------------------
def point_to_segment_distance(
    p_lat: float, p_lng: float,
    seg_a: list[float], seg_b: list[float],
) -> float:
    """Minimum distance in meters from point to line segment [seg_a, seg_b].

    seg_a, seg_b are [lng, lat]. Uses projection onto the segment
    with clamping to endpoints.
    """
    a_lng, a_lat = seg_a
    b_lng, b_lat = seg_b

    # Bbox pre-check: if point is clearly far from segment, skip expensive math
    lat_min = min(a_lat, b_lat) - 0.02  # ~2.2 km margin
    lat_max = max(a_lat, b_lat) + 0.02
    lng_min = min(a_lng, b_lng) - 0.025
    lng_max = max(a_lng, b_lng) + 0.025
    if p_lat < lat_min or p_lat > lat_max or p_lng < lng_min or p_lng > lng_max:
        return float("inf")

    d_a = haversine_m(p_lat, p_lng, a_lat, a_lng)
    d_b = haversine_m(p_lat, p_lng, b_lat, b_lng)
    d_ab = haversine_m(a_lat, a_lng, b_lat, b_lng)

    if d_ab < 1.0:
        return d_a

    # Project point onto segment using normalized dot product approximation
    # This uses a flat-earth approximation for the projection (acceptable at segment scale)
    dx = b_lng - a_lng
    dy = b_lat - a_lat
    t = ((p_lng - a_lng) * dx + (p_lat - a_lat) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))

    proj_lng = a_lng + t * dx
    proj_lat = a_lat + t * dy

    return haversine_m(p_lat, p_lng, proj_lat, proj_lng)


# ---------------------------------------------------------------------------
# Corridor filter
# ---------------------------------------------------------------------------
def corridor_filter(
    route: list[list[float]],
    candidates: list[dict],
    corridor_width_m: float = CORRIDOR_WIDTH_M,
    interval_m: Optional[float] = None,
) -> list[dict]:
    """Filter candidates to those within corridor_width_m of the route.

    Route is [[lng, lat], ...]. Candidates are dicts with 'lat' and 'lon' keys.
    Returns candidates with 'distance_along_route_m' added, sorted by that value.
    """
    if len(route) < 2 or not candidates:
        return []

    # Simplify route for faster checks
    simplified = douglas_peucker(route, tolerance_m=50.0)

    # Pre-compute cumulative segment lengths for distance-along-route
    cum_lengths = [0.0]
    for i in range(1, len(simplified)):
        seg_len = haversine_m(
            simplified[i - 1][1], simplified[i - 1][0],
            simplified[i][1], simplified[i][0],
        )
        cum_lengths.append(cum_lengths[-1] + seg_len)

    results = []
    for cand in candidates:
        p_lat = float(cand["lat"])
        p_lng = float(cand["lon"])

        min_dist = float("inf")
        best_seg_idx = 0
        best_t = 0.0

        for i in range(len(simplified) - 1):
            seg_a = simplified[i]
            seg_b = simplified[i + 1]

            d = point_to_segment_distance(p_lat, p_lng, seg_a, seg_b)
            if d < min_dist:
                min_dist = d
                best_seg_idx = i
                # Compute t for distance-along-route
                dx = seg_b[0] - seg_a[0]
                dy = seg_b[1] - seg_a[1]
                denom = dx * dx + dy * dy
                if denom > 0:
                    best_t = max(0.0, min(1.0,
                        ((p_lng - seg_a[0]) * dx + (p_lat - seg_a[1]) * dy) / denom
                    ))
                else:
                    best_t = 0.0

        if min_dist <= corridor_width_m:
            seg_len = haversine_m(
                simplified[best_seg_idx][1], simplified[best_seg_idx][0],
                simplified[best_seg_idx + 1][1], simplified[best_seg_idx + 1][0],
            )
            dist_along = cum_lengths[best_seg_idx] + best_t * seg_len

            result = dict(cand)
            result["distance_along_route_m"] = round(dist_along, 1)
            results.append(result)

    # Sort by distance along route
    results.sort(key=lambda r: r["distance_along_route_m"])

    # Interval filter: keep closest result per interval
    if interval_m and interval_m > 0 and results:
        total_route_length = cum_lengths[-1]
        filtered = []
        marker = 0.0
        while marker <= total_route_length:
            best = None
            best_diff = float("inf")
            for r in results:
                diff = abs(r["distance_along_route_m"] - marker)
                if diff < best_diff:
                    best_diff = diff
                    best = r
            if best and best not in filtered:
                filtered.append(best)
            marker += interval_m
        results = filtered

    return results


def distance_along_polyline(polyline: list[list[float]]) -> float:
    """Total length of a [lng, lat] polyline in meters."""
    total = 0.0
    for i in range(1, len(polyline)):
        total += haversine_m(
            polyline[i - 1][1], polyline[i - 1][0],
            polyline[i][1], polyline[i][0],
        )
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_corridor.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/search/spatial.py tests/test_corridor.py
git commit -m "feat: corridor math — Douglas-Peucker, segment distance, corridor filter"
```

---

## Task 3: POST /search/spatial Endpoint

**Files:**
- Modify: `services/search/main.py` — add POI lat/lon index, import spatial router
- Modify: `services/search/spatial.py` — add the FastAPI endpoint that wires together intent parsing, Nominatim/POI queries, and corridor filtering
- Create: `tests/test_spatial_endpoint.py`

- [ ] **Step 1: Write failing tests for the endpoint**

```python
# tests/test_spatial_endpoint.py
"""Integration tests for POST /search/spatial."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


class TestSpatialEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Import app after patching dependencies."""
        # Patch aiosqlite and httpx before importing the app
        with patch("main.aiosqlite") as mock_sqlite, \
             patch("main.httpx") as mock_httpx:
            mock_sqlite.connect = AsyncMock()
            from main import app
            self.client = TestClient(app)

    def test_plain_search(self):
        resp = self.client.post("/spatial", json={
            "query": "Phoenix",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "plain"
        assert data["original_intent"] == "plain"
        assert data["fallback_reason"] is None

    def test_proximity_search(self):
        resp = self.client.post("/spatial", json={
            "query": "nearest gas station",
            "position": {"lat": 33.45, "lon": -112.07},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "proximity"
        assert data["category"] == "gas station"

    def test_proximity_fallback_no_position(self):
        resp = self.client.post("/spatial", json={
            "query": "nearest gas station",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "plain"
        assert data["original_intent"] == "proximity"
        assert data["fallback_reason"] == "no_position"

    def test_query_too_long(self):
        resp = self.client.post("/spatial", json={
            "query": "x" * 501,
        })
        assert resp.status_code == 422

    def test_route_too_many_points(self):
        resp = self.client.post("/spatial", json={
            "query": "gas along my route",
            "route": [[-112.0, 33.0]] * 10001,
        })
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_spatial_endpoint.py -v`
Expected: FAIL (no `/spatial` endpoint exists)

- [ ] **Step 3: Add the spatial endpoint to spatial.py and wire it into main.py**

Add to `services/search/spatial.py` (at the end of the file):

```python
# ---------------------------------------------------------------------------
# FastAPI endpoint
# ---------------------------------------------------------------------------
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()


class PositionBody(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class SpatialSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    position: Optional[PositionBody] = None
    route: Optional[list[list[float]]] = Field(None, max_length=10000)


async def _spatial_search(
    body: SpatialSearchBody,
    query_nominatim,
    query_poi,
    deduplicate,
) -> dict:
    """Core spatial search logic. Accepts injected query functions for testability."""
    import asyncio

    parsed = parse_intent(
        body.query,
        has_position=body.position is not None,
        has_route=body.route is not None and len(body.route) >= 2,
    )

    search_text = parsed["search_text"]
    intent = parsed["intent"]

    # Build bbox for spatial queries
    bbox = None
    if intent == "route_corridor" and body.route:
        lngs = [p[0] for p in body.route]
        lats = [p[1] for p in body.route]
        margin = 0.02  # ~2.2 km
        bbox = f"{min(lngs)-margin},{min(lats)-margin},{max(lngs)+margin},{max(lats)+margin}"
    elif intent == "proximity" and body.position:
        radius_m = parsed["radius_m"] or DEFAULT_PROXIMITY_RADIUS_M
        # Convert radius to rough degree margin
        margin = radius_m / 111_000  # ~111 km per degree
        bbox = (
            f"{body.position.lon - margin},{body.position.lat - margin},"
            f"{body.position.lon + margin},{body.position.lat + margin}"
        )

    # Query both sources
    limit = 20  # fetch more than we show, filter down
    nom_task = asyncio.create_task(query_nominatim(search_text, limit, bbox))
    poi_task = asyncio.create_task(query_poi(search_text, limit, bbox,
                                             gnis_class=parsed.get("gnis_class")))
    nom_results, poi_results = await asyncio.gather(nom_task, poi_task, return_exceptions=True)
    if isinstance(nom_results, BaseException):
        nom_results = []
    if isinstance(poi_results, BaseException):
        poi_results = []

    merged = deduplicate(nom_results, poi_results)

    # Add distance_m if position available
    if body.position:
        for r in merged:
            try:
                r["distance_m"] = round(haversine_m(
                    body.position.lat, body.position.lon,
                    float(r["lat"]), float(r["lon"])
                ), 1)
            except (KeyError, TypeError, ValueError):
                r["distance_m"] = None
    else:
        for r in merged:
            r["distance_m"] = None

    # Apply spatial filtering
    if intent == "route_corridor" and body.route:
        merged = corridor_filter(
            body.route, merged,
            corridor_width_m=CORRIDOR_WIDTH_M,
            interval_m=parsed.get("interval_m"),
        )
    elif intent == "proximity":
        # Sort by distance, apply radius
        merged = [r for r in merged if r.get("distance_m") is not None]
        merged.sort(key=lambda r: r["distance_m"])
        radius = parsed["radius_m"] or DEFAULT_PROXIMITY_RADIUS_M
        merged = [r for r in merged if r["distance_m"] <= radius]

    # Add null distance_along_route_m for non-corridor results
    for r in merged:
        if "distance_along_route_m" not in r:
            r["distance_along_route_m"] = None

    return {
        "results": merged[:10],
        "intent": parsed["intent"],
        "original_intent": parsed["original_intent"],
        "fallback_reason": parsed["fallback_reason"],
        "category": parsed["category"],
    }
```

Add to `services/search/main.py` — at the top with other imports:

```python
from spatial import router as spatial_router
```

After the `app = FastAPI(...)` line:

```python
app.include_router(spatial_router, prefix="")
```

In the `lifespan` function, after opening the POI database, add the lat/lon index:

```python
        # Ensure lat/lon index for bbox queries
        if state.poi_db:
            await state.poi_db.execute(
                "CREATE INDEX IF NOT EXISTS idx_poi_latlon ON poi_features (lat, lon)"
            )
```

Add the route handler in `spatial.py`:

```python
@router.post("/spatial")
async def spatial_search(body: SpatialSearchBody):
    """Natural language spatial search endpoint."""
    from main import _query_nominatim, _query_poi, _deduplicate, state

    # Wrap _query_poi to support optional gnis_class filter
    async def query_poi_with_class(q, limit, bbox, gnis_class=None):
        results = await _query_poi(q, limit, bbox)
        if gnis_class and results:
            # Boost GNIS class matches to top
            class_matches = [r for r in results if r.get("class", "").lower() == gnis_class.lower()]
            others = [r for r in results if r.get("class", "").lower() != gnis_class.lower()]
            return class_matches + others
        return results

    return await _spatial_search(
        body, _query_nominatim, query_poi_with_class, _deduplicate
    )
```

- [ ] **Step 4: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: All tests PASS (intent parser + corridor + endpoint)

- [ ] **Step 5: Commit**

```bash
git add services/search/spatial.py services/search/main.py tests/test_spatial_endpoint.py
git commit -m "feat: POST /search/spatial endpoint with intent parsing and corridor search"
```

---

## Task 4: Frontend — POST Switch + Route Coords State

**Files:**
- Modify: `frontend/app.js`

This task switches the frontend to POST /search/spatial and stores decoded route coordinates for search context. No UI changes yet — just the data plumbing.

- [ ] **Step 1: Add `lastRouteCoords` state variable**

At `frontend/app.js` near line 43 (where `lastRouteTrip` is declared), add:

```javascript
  var lastRouteCoords = null;  // decoded [lng, lat] pairs for spatial search context
```

- [ ] **Step 2: Populate `lastRouteCoords` in `renderRoute()`**

In `renderRoute()` (around line 1062), after the loop that decodes polylines and builds `allCoords`, add:

```javascript
      // Store decoded coords for spatial search context
      lastRouteCoords = allCoords.slice();
```

- [ ] **Step 3: Clear `lastRouteCoords` in `clearRoute()`**

In `clearRoute()` (find it by searching for `lastRouteTrip = null`), add alongside it:

```javascript
      lastRouteCoords = null;
```

- [ ] **Step 4: Switch `performSearch()` to POST /search/spatial**

Replace the existing `performSearch()` function:

```javascript
  function performSearch(query) {
    var body = { query: query };

    // Enrich with GPS position if available
    if (gpsLastPos && !gpsStale) {
      body.position = { lat: gpsLastPos[1], lon: gpsLastPos[0] };
    }

    // Enrich with route geometry if available
    if (lastRouteCoords && lastRouteCoords.length >= 2) {
      body.route = lastRouteCoords;
    }

    fetch('/search/spatial', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })
      .then(function (res) {
        if (res.status === 404 || res.status === 405) {
          // Fallback to old endpoint if backend hasn't been updated
          return fetch('/search/search?q=' + encodeURIComponent(query) + '&limit=10')
            .then(function (r) { return r.json(); })
            .then(function (d) { return { results: d.results || d, intent: 'plain', original_intent: 'plain', fallback_reason: null, category: null }; });
        }
        return res.json();
      })
      .then(function (data) {
        renderSearchResults(data.results || [], data);
      })
      .catch(function (err) {
        console.error('Search error:', err);
      });
  }
```

- [ ] **Step 5: Update `renderSearchResults` signature to accept metadata**

Change the function signature from `renderSearchResults(results)` to `renderSearchResults(results, metadata)` and pass `metadata` through. For now the metadata is unused — the next task adds UI for it.

```javascript
  function renderSearchResults(results, metadata) {
    // ... existing code unchanged for now ...
  }
```

- [ ] **Step 6: Verify syntax and test manually**

```bash
node -c frontend/app.js
curl -s -o /dev/null -w "%{http_code}" https://pandora.twin-bramble.ts.net/
```

Expected: Syntax OK, HTTP 200

- [ ] **Step 7: Commit**

```bash
git add frontend/app.js
git commit -m "feat: switch search to POST /search/spatial with GPS and route context"
```

---

## Task 5: Frontend — Numbered Pins for All Search Results

**Files:**
- Modify: `frontend/app.js`

This task adds numbered map pins for ALL search results (plain and spatial), replacing the old single-marker approach.

- [ ] **Step 1: Register `search-results` source and layer in `addPlaceholderSources()`**

In `addPlaceholderSources()` (around line 89), add at the END of the function (after all other layer registrations):

```javascript
    // --- Search result pins (numbered markers for all searches) ---
    if (!map.getSource('search-results')) {
      map.addSource('search-results', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] }
      });
    }
    if (!map.getLayer('search-result-circles')) {
      map.addLayer({
        id: 'search-result-circles',
        type: 'circle',
        source: 'search-results',
        paint: {
          'circle-radius': 14,
          'circle-color': '#e6920a',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 2
        }
      });
    }
    if (!map.getLayer('search-result-labels')) {
      map.addLayer({
        id: 'search-result-labels',
        type: 'symbol',
        source: 'search-results',
        layout: {
          'text-field': ['get', 'index'],
          'text-size': 12,
          'text-allow-overlap': true,
          'text-ignore-placement': true,
        },
        paint: {
          'text-color': '#ffffff',
        }
      });
    }
```

- [ ] **Step 2: Add pin click handler and cursor change in `initSearch()`**

In `initSearch()`, after the existing event listeners:

```javascript
    // Search pin click handler
    map.on('click', 'search-result-circles', function (e) {
      if (!e.features || !e.features.length) return;
      var idx = e.features[0].properties.index - 1;
      var items = document.querySelectorAll('#search-results li');
      if (items[idx]) {
        items[idx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        // Highlight briefly
        items[idx].classList.add('search-result-active');
        setTimeout(function () { items[idx].classList.remove('search-result-active'); }, 2000);
      }
    });

    // Pointer cursor on pin hover
    map.on('mouseenter', 'search-result-circles', function () {
      map.getCanvas().style.cursor = 'pointer';
    });
    map.on('mouseleave', 'search-result-circles', function () {
      map.getCanvas().style.cursor = '';
    });
```

- [ ] **Step 3: Add `clearSearchPins()` and `updateSearchPins()` functions**

```javascript
  function clearSearchPins() {
    var src = map.getSource('search-results');
    if (src) src.setData({ type: 'FeatureCollection', features: [] });
  }

  function updateSearchPins(results) {
    var features = results.map(function (item, i) {
      var lng = parseFloat(item.lon || item.lng || item.longitude);
      var lat = parseFloat(item.lat || item.latitude);
      if (isNaN(lng) || isNaN(lat)) return null;
      return {
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [lng, lat] },
        properties: {
          index: String(i + 1),
          name: item.name || item.display_name || 'Result',
          display_name: item.display_name || item.name || '',
        }
      };
    }).filter(Boolean);

    var src = map.getSource('search-results');
    if (src) src.setData({ type: 'FeatureCollection', features: features });
  }
```

- [ ] **Step 4: Rewrite `renderSearchResults()` with numbered badges and distance**

```javascript
  function renderSearchResults(results, metadata) {
    var list = document.getElementById('search-results');
    while (list.firstChild) list.removeChild(list.firstChild);

    // Clear previous pins
    clearSearchPins();

    if (!results || results.length === 0) {
      var emptyLi = document.createElement('li');
      // Show contextual message for spatial queries with no results
      if (metadata && metadata.original_intent !== 'plain' && metadata.fallback_reason) {
        if (metadata.fallback_reason === 'no_position') {
          emptyLi.textContent = 'Enable GPS for proximity search';
        } else if (metadata.fallback_reason === 'no_route') {
          emptyLi.textContent = 'Set a route for corridor search';
        } else {
          emptyLi.textContent = 'No results found';
        }
      } else if (metadata && metadata.intent !== 'plain') {
        emptyLi.textContent = 'No ' + (metadata.category || 'results') + ' found nearby';
      } else {
        emptyLi.textContent = 'No results found';
      }
      list.appendChild(emptyLi);
      list.classList.add('visible');
      return;
    }

    // Intent subtitle
    if (metadata && metadata.intent !== 'plain' && metadata.category) {
      var subtitleLi = document.createElement('li');
      subtitleLi.className = 'search-intent-subtitle';
      if (metadata.intent === 'route_corridor') {
        subtitleLi.textContent = (metadata.category.charAt(0).toUpperCase() + metadata.category.slice(1)) + ' along route';
      } else {
        subtitleLi.textContent = 'Nearest ' + metadata.category;
      }
      list.appendChild(subtitleLi);
    }

    results.forEach(function (item, idx) {
      var li = document.createElement('li');

      // Numbered badge
      var badge = document.createElement('span');
      badge.className = 'search-result-badge';
      badge.textContent = String(idx + 1);
      li.appendChild(badge);

      // Name
      var nameSpan = document.createElement('span');
      nameSpan.className = 'search-result-name';
      nameSpan.textContent = item.name || item.display_name || 'Unknown';
      li.appendChild(nameSpan);

      // Distance badge (spatial results only)
      if (item.distance_along_route_m != null) {
        var distSpan = document.createElement('span');
        distSpan.className = 'search-result-distance';
        distSpan.textContent = 'in ' + formatDistance(item.distance_along_route_m);
        li.appendChild(distSpan);
      } else if (item.distance_m != null) {
        var distSpan2 = document.createElement('span');
        distSpan2.className = 'search-result-distance';
        distSpan2.textContent = formatDistance(item.distance_m);
        li.appendChild(distSpan2);
      }

      li.addEventListener('click', function () {
        selectSearchResult(item, idx);
      });
      list.appendChild(li);
    });

    // Drop numbered pins on map
    updateSearchPins(results);

    list.classList.add('visible');
  }
```

- [ ] **Step 5: Replace `selectSearchResult()` — remove old marker, use pin fly-to**

```javascript
  function selectSearchResult(item, idx) {
    var lng = parseFloat(item.lon || item.longitude || item.lng);
    var lat = parseFloat(item.lat || item.latitude);
    if (isNaN(lng) || isNaN(lat)) return;

    // Fly to pin with padding to avoid sidebar occlusion
    map.flyTo({
      center: [lng, lat],
      zoom: Math.max(map.getZoom(), 14),
      padding: { bottom: 200, left: 0, right: 0, top: 0 }
    });

    // Open a popup at the pin location
    if (searchPopup) searchPopup.remove();
    var popupContent = document.createElement('div');
    var h4 = document.createElement('h4');
    h4.textContent = (item.name || item.display_name || 'Result');
    popupContent.appendChild(h4);
    if (item.display_name && item.display_name !== item.name) {
      var p = document.createElement('p');
      p.textContent = item.display_name;
      p.style.fontSize = '12px';
      p.style.color = '#666';
      popupContent.appendChild(p);
    }

    searchPopup = new maplibregl.Popup({ offset: 25, closeOnClick: true })
      .setLngLat([lng, lat])
      .setDOMContent(popupContent)
      .addTo(map);
  }
```

- [ ] **Step 6: Update `hideSearchResults()` to clear pins**

```javascript
  function hideSearchResults() {
    document.getElementById('search-results').classList.remove('visible');
    clearSearchPins();
    if (searchPopup) { searchPopup.remove(); searchPopup = null; }
  }
```

- [ ] **Step 7: Remove old `searchMarker` variable and its usage**

Remove the `var searchMarker = null;` declaration (around line 35) and all references to it. The numbered pins and popup replace this. Also remove the old `if (searchMarker) searchMarker.remove();` lines.

- [ ] **Step 8: Add CSS for search result badges and distance**

In `frontend/style.css`, add:

```css
.search-result-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #e6920a;
  color: #fff;
  font-size: 11px;
  font-weight: bold;
  margin-right: 8px;
  flex-shrink: 0;
}

.search-result-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.search-result-distance {
  color: #888;
  font-size: 12px;
  margin-left: 8px;
  white-space: nowrap;
}

.search-intent-subtitle {
  font-size: 11px;
  color: #888;
  font-style: italic;
  padding: 4px 12px;
  border-bottom: 1px solid #eee;
  pointer-events: none;
}

.search-result-active {
  background: #fff3cd !important;
  transition: background 0.3s;
}

#search-results li {
  display: flex;
  align-items: center;
}
```

- [ ] **Step 9: Verify syntax, test manually, commit**

```bash
node -c frontend/app.js
curl -s -o /dev/null -w "%{http_code}" https://pandora.twin-bramble.ts.net/
```

Expected: Syntax OK, HTTP 200. Search results should show numbered badges.

```bash
git add frontend/app.js frontend/style.css
git commit -m "feat: numbered search pins for all results with distance badges"
```

---

## Task 6: End-to-End Verification

**Files:** None (testing only)

- [ ] **Step 1: Run all Python tests**

```bash
python3 -m pytest tests/ -v
```

Expected: All tests pass (intent parser + corridor + endpoint + earlier pipeline tests)

- [ ] **Step 2: Test plain search (no regression)**

Open `https://pandora.twin-bramble.ts.net`, type "Phoenix" in search, press Enter. Verify:
- Results appear in dropdown with numbered badges
- Numbered amber pins appear on map
- Clicking a result flies to the pin
- Clicking outside dismisses results and clears pins

- [ ] **Step 3: Test proximity search**

With GPS enabled (server or device), type "nearest gas station" and press Enter. Verify:
- Intent subtitle shows "Nearest gas station"
- Results have distance badges ("2.3 mi" or "3.7 km")
- Results are sorted by distance (closest first)
- Pins on map match result numbers

- [ ] **Step 4: Test corridor search**

Set a route (e.g., Phoenix to Flagstaff). Type "gas stations along my route" and press Enter. Verify:
- Intent subtitle shows "Gas stations along route"
- Results have "in X mi" distance-along-route badges
- Results are sorted by distance along route
- Only results near the route corridor appear

- [ ] **Step 5: Test fallback behavior**

Without GPS, type "nearest hospital". Verify:
- Results appear (plain search fallback)
- No distance badges (no position available)

Without a route, type "gas stations along my route". Verify:
- Falls back to proximity search (if GPS available) or plain search (if not)
- Hint message shown if applicable

- [ ] **Step 6: Commit any fixes from testing**

```bash
git add -A
git commit -m "fix: end-to-end testing adjustments for spatial search"
```
