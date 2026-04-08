"""Natural language spatial search — intent parser, synonym table, corridor math.

This module provides the core logic for POST /search/spatial:
- Intent detection (rule-based regex)
- Category extraction (synonym table + fallback)
- Corridor search (Douglas-Peucker simplification + segment distance)
- Spatial endpoint (FastAPI router)
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
SYNONYM_TABLE = [
    # Road trip / commercial (Nominatim primary)
    {"synonyms": {"gas station", "fuel", "gas"}, "gnis_class": None, "fallback_text": "gas station"},
    {"synonyms": {"restaurant", "food", "eat", "dining"}, "gnis_class": None, "fallback_text": "restaurant"},
    {"synonyms": {"hotel", "motel", "lodging"}, "gnis_class": None, "fallback_text": "hotel"},
    {"synonyms": {"hospital", "er", "emergency room"}, "gnis_class": "Hospital", "fallback_text": "hospital"},
    {"synonyms": {"campground", "camping", "campsite"}, "gnis_class": None, "fallback_text": "campground"},
    {"synonyms": {"rest area", "rest stop"}, "gnis_class": None, "fallback_text": "rest area"},
    {"synonyms": {"pharmacy", "drugstore"}, "gnis_class": None, "fallback_text": "pharmacy"},
    {"synonyms": {"grocery", "supermarket"}, "gnis_class": None, "fallback_text": "grocery"},
    # Geographic / emergency ops (GNIS supplementary)
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

# Build flat lookup: normalized synonym text -> table entry
_SYNONYM_LOOKUP: dict[str, dict] = {}
for _entry in SYNONYM_TABLE:
    for _syn in _entry["synonyms"]:
        _SYNONYM_LOOKUP[_syn.lower()] = _entry

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------
# Route corridor (checked first)
RE_ALONG_ROUTE = re.compile(r'\balong\s+(my\s+)?route\b', re.IGNORECASE)
RE_ON_ROUTE = re.compile(r'\bon\s+(my\s+)?route\b', re.IGNORECASE)
RE_EVERY_N = re.compile(r'\bevery\s+(\d+)\s+(miles?|km|kilometers?)\b', re.IGNORECASE)

# Proximity
RE_NEAREST = re.compile(r'\bnearest\s+', re.IGNORECASE)
RE_CLOSEST = re.compile(r'\bclosest\s+', re.IGNORECASE)
RE_NEAR_ME = re.compile(r'\bnear\s+me\b', re.IGNORECASE)
RE_NEAR_HERE = re.compile(r'\bnear\s+here\b', re.IGNORECASE)
RE_NEARBY = re.compile(r'\bnearby\s+', re.IGNORECASE)
RE_WITHIN = re.compile(r'\bwithin\s+(\d+)\s+(miles?|km|kilometers?|mi)\b', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _strip_filler(text: str) -> str:
    """Remove common filler words from extracted category text."""
    tokens = text.split()
    return " ".join(t for t in tokens if t.lower() not in FILLER_WORDS)


def _lookup_category(text: str) -> tuple[Optional[dict], str]:
    """Look up category in synonym table. Returns (entry, search_text).

    Token-based matching with plural normalization:
    1. Try exact match on full text
    2. Try with trailing 's' stripped (plural normalization)
    3. Try each token individually
    """
    normalized = text.strip().lower()
    if not normalized:
        return None, text

    # Exact match
    if normalized in _SYNONYM_LOOKUP:
        entry = _SYNONYM_LOOKUP[normalized]
        return entry, entry["fallback_text"]

    # Plural normalization: strip trailing 's'
    if normalized.endswith("s") and normalized[:-1] in _SYNONYM_LOOKUP:
        entry = _SYNONYM_LOOKUP[normalized[:-1]]
        return entry, entry["fallback_text"]

    # Multi-word plural: "gas stations" -> "gas station"
    if normalized.endswith("s"):
        singular = normalized[:-1]
        if singular in _SYNONYM_LOOKUP:
            entry = _SYNONYM_LOOKUP[singular]
            return entry, entry["fallback_text"]

    # Token-level match
    tokens = normalized.split()
    for token in tokens:
        if token in _SYNONYM_LOOKUP:
            entry = _SYNONYM_LOOKUP[token]
            return entry, entry["fallback_text"]
        if token.endswith("s") and token[:-1] in _SYNONYM_LOOKUP:
            entry = _SYNONYM_LOOKUP[token[:-1]]
            return entry, entry["fallback_text"]

    # No match — return raw text
    return None, text.strip()


def _parse_unit_to_meters(value: int, unit: str) -> float:
    """Convert a distance value + unit string to meters."""
    unit = unit.lower().rstrip("s")  # "miles" -> "mile"
    if unit in ("mile", "mi"):
        return value * MILES_TO_METERS
    return value * KM_TO_METERS


# ---------------------------------------------------------------------------
# Intent parser
# ---------------------------------------------------------------------------
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
    """Approximate perpendicular distance from point to line AB in meters."""
    d_ap = haversine_m(plat, plng, a_lat, a_lng)
    d_ab = haversine_m(a_lat, a_lng, b_lat, b_lng)
    if d_ab < 1.0:
        return d_ap
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

    seg_a, seg_b are [lng, lat]. Includes bbox pre-check for performance.
    """
    a_lng, a_lat = seg_a
    b_lng, b_lat = seg_b

    # Bbox pre-check: skip expensive trig for clearly distant points
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

    # Project point onto segment using flat-earth approximation (fine at segment scale)
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

    simplified = douglas_peucker(route, tolerance_m=50.0)

    # Pre-compute cumulative segment lengths
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


# ---------------------------------------------------------------------------
# FastAPI endpoint
# ---------------------------------------------------------------------------
import asyncio
from fastapi import APIRouter
from pydantic import BaseModel, Field
from typing import Optional as Opt

router = APIRouter()


class PositionBody(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class SpatialSearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    position: Opt[PositionBody] = None
    route: Opt[list[list[float]]] = Field(None, max_length=10000)


@router.post("/spatial")
async def spatial_search(body: SpatialSearchBody):
    """Natural language spatial search endpoint."""
    # Deferred import to avoid circular dependency (main imports router from this file)
    from main import _query_nominatim, _query_poi, _deduplicate

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
        margin = radius_m / 111_000  # ~111 km per degree
        bbox = (
            f"{body.position.lon - margin},{body.position.lat - margin},"
            f"{body.position.lon + margin},{body.position.lat + margin}"
        )

    # Query both sources in parallel
    limit = 20
    nom_results, poi_results = await asyncio.gather(
        _query_nominatim(search_text, limit, bbox),
        _query_poi(search_text, limit, bbox),
        return_exceptions=True,
    )
    if isinstance(nom_results, BaseException):
        nom_results = []
    if isinstance(poi_results, BaseException):
        poi_results = []

    # Boost GNIS class matches when a class is specified
    gnis_class = parsed.get("gnis_class")
    if gnis_class and poi_results:
        class_matches = [r for r in poi_results if (r.get("class") or "").lower() == gnis_class.lower()]
        others = [r for r in poi_results if (r.get("class") or "").lower() != gnis_class.lower()]
        poi_results = class_matches + others

    merged = _deduplicate(nom_results, poi_results)

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
        merged = [r for r in merged if r.get("distance_m") is not None]
        merged.sort(key=lambda r: r["distance_m"])
        radius = parsed["radius_m"] or DEFAULT_PROXIMITY_RADIUS_M
        merged = [r for r in merged if r["distance_m"] <= radius]

    # Ensure all results have both distance fields
    for r in merged:
        if "distance_along_route_m" not in r:
            r["distance_along_route_m"] = None
        if "distance_m" not in r:
            r["distance_m"] = None

    return {
        "results": merged[:10],
        "intent": parsed["intent"],
        "original_intent": parsed["original_intent"],
        "fallback_reason": parsed["fallback_reason"],
        "category": parsed["category"],
    }
