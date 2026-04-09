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

COMPOUND_IN_PHRASES = {"drive in", "check in", "walk in", "plug in", "built in",
                       "dine in", "sign in", "log in", "trade in", "break in"}

# ---------------------------------------------------------------------------
# Synonym table
# ---------------------------------------------------------------------------
SYNONYM_TABLE = [
    # Road trip / commercial (Nominatim primary)
    # nominatim_query: search terms that Nominatim recognizes
    # osm_types: accepted Nominatim category/type pairs for post-filtering false positives
    #   None means no filtering (accept all results)
    {"synonyms": {"gas station", "fuel", "gas"}, "gnis_class": None, "fallback_text": "gas station",
     "nominatim_query": ["fuel station", "gas", "Shell", "Chevron", "ARCO", "76", "Mobil", "Circle K"],
     "osm_types": {("amenity", "fuel"), ("shop", "gas"), ("shop", "convenience")}},
    {"synonyms": {"restaurant", "food", "eat", "dining"}, "gnis_class": None, "fallback_text": "restaurant",
     "nominatim_query": ["restaurant"],
     "osm_types": {("amenity", "restaurant"), ("amenity", "fast_food"), ("amenity", "cafe")}},
    {"synonyms": {"hotel", "motel", "lodging"}, "gnis_class": None, "fallback_text": "hotel",
     "nominatim_query": ["hotel", "motel"],
     "osm_types": {("tourism", "hotel"), ("tourism", "motel"), ("building", "hotel")}},
    {"synonyms": {"hospital", "er", "emergency room"}, "gnis_class": "Hospital", "fallback_text": "hospital",
     "nominatim_query": ["hospital"],
     "osm_types": {("amenity", "hospital"), ("building", "hospital")}},
    {"synonyms": {"campground", "camping", "campsite"}, "gnis_class": None, "fallback_text": "campground",
     "nominatim_query": ["camp site", "campground"],
     "osm_types": {("tourism", "camp_site"), ("tourism", "caravan_site"), ("leisure", "park")}},
    {"synonyms": {"rest area", "rest stop"}, "gnis_class": None, "fallback_text": "rest area",
     "nominatim_query": ["rest area"],
     "osm_types": {("highway", "rest_area"), ("highway", "services")}},
    {"synonyms": {"pharmacy", "drugstore"}, "gnis_class": None, "fallback_text": "pharmacy",
     "nominatim_query": ["pharmacy"],
     "osm_types": {("amenity", "pharmacy"), ("shop", "chemist")}},
    {"synonyms": {"grocery", "supermarket"}, "gnis_class": None, "fallback_text": "grocery",
     "nominatim_query": ["supermarket", "grocery"],
     "osm_types": {("shop", "supermarket"), ("shop", "convenience"), ("shop", "grocery")}},
    # Geographic / emergency ops (GNIS supplementary — osm_types=None, no filtering)
    {"synonyms": {"water", "drinking water"}, "gnis_class": "Spring", "fallback_text": "water",
     "nominatim_query": ["drinking water"], "osm_types": {("amenity", "drinking_water")}},
    {"synonyms": {"trailhead", "trail"}, "gnis_class": "Trail", "fallback_text": "trailhead",
     "nominatim_query": ["trailhead"], "osm_types": None},
    {"synonyms": {"park"}, "gnis_class": "Park", "fallback_text": "park",
     "nominatim_query": ["park"], "osm_types": {("leisure", "park"), ("boundary", "national_park")}},
    {"synonyms": {"school"}, "gnis_class": "School", "fallback_text": "school",
     "nominatim_query": ["school"], "osm_types": {("amenity", "school"), ("building", "school")}},
    {"synonyms": {"church"}, "gnis_class": "Church", "fallback_text": "church",
     "nominatim_query": ["church"], "osm_types": {("amenity", "place_of_worship"), ("building", "church")}},
    {"synonyms": {"airport"}, "gnis_class": "Airport", "fallback_text": "airport",
     "nominatim_query": ["airport"], "osm_types": {("aeroway", "aerodrome")}},
    {"synonyms": {"fire station"}, "gnis_class": None, "fallback_text": "fire station",
     "nominatim_query": ["fire station"], "osm_types": {("amenity", "fire_station")}},
    {"synonyms": {"police", "police station"}, "gnis_class": None, "fallback_text": "police station",
     "nominatim_query": ["police"], "osm_types": {("amenity", "police")}},
    {"synonyms": {"summit", "peak", "hilltop", "mountain"}, "gnis_class": "Summit", "fallback_text": "summit",
     "nominatim_query": ["peak", "summit"], "osm_types": {("natural", "peak"), ("natural", "volcano")}},
    {"synonyms": {"tower", "radio tower", "repeater", "comm site"}, "gnis_class": "Tower", "fallback_text": "tower",
     "nominatim_query": ["tower"], "osm_types": {("man_made", "tower"), ("man_made", "mast")}},
    {"synonyms": {"shelter", "evacuation center", "evac"}, "gnis_class": None, "fallback_text": "shelter",
     "nominatim_query": ["shelter"], "osm_types": None},
    {"synonyms": {"helipad", "landing zone", "lz"}, "gnis_class": None, "fallback_text": "helipad",
     "nominatim_query": ["helipad"], "osm_types": {("aeroway", "helipad")}},
    {"synonyms": {"dam"}, "gnis_class": "Dam", "fallback_text": "dam",
     "nominatim_query": ["dam"], "osm_types": {("waterway", "dam")}},
    {"synonyms": {"mine", "quarry"}, "gnis_class": "Mine", "fallback_text": "mine",
     "nominatim_query": ["mine"], "osm_types": {("landuse", "quarry")}},
    {"synonyms": {"spring", "hot spring"}, "gnis_class": "Spring", "fallback_text": "spring",
     "nominatim_query": ["spring"], "osm_types": {("natural", "spring")}},
    {"synonyms": {"bridge"}, "gnis_class": "Bridge", "fallback_text": "bridge",
     "nominatim_query": ["bridge"], "osm_types": {("man_made", "bridge")}},
    {"synonyms": {"ranger station", "forest service"}, "gnis_class": "Locale", "fallback_text": "ranger station",
     "nominatim_query": ["ranger station"], "osm_types": None},
    # Public land (OSM POI primary -- requires osm_operator disambiguation)
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


def _extract_place(text: str) -> tuple[str, Optional[str]]:
    """Extract place name from ' in <place>' pattern at end of text.

    Returns (before_text, place_name) or (original_text, None).
    Uses space-bounded matching only (no \\b word boundary) because
    Python's \\b matches at hyphens, breaking compound phrases like 'drive-in'.
    """
    lowered = text.lower()

    # Find all space-bounded " in " positions, plus " in" at end of string
    candidates = []
    start = 0
    while True:
        pos = lowered.find(" in ", start)
        if pos == -1:
            break
        candidates.append(pos)
        start = pos + 1

    # Also check for " in" at the very end (no place after)
    if lowered.endswith(" in"):
        candidates.append(len(text) - 3)

    if not candidates:
        return text, None

    # Process candidates right to left (prefer LAST valid "in")
    for pos in reversed(candidates):
        before_in = text[:pos]
        after_in = text[pos + 4:] if pos + 4 <= len(text) else ""

        # Check if this "in" is part of a compound phrase
        # Normalize hyphens to spaces before checking
        before_normalized = before_in.replace("-", " ").lower()
        is_compound = False
        for phrase in COMPOUND_IN_PHRASES:
            if before_normalized.endswith(phrase.rsplit(" ", 1)[0]):
                # e.g. before_normalized ends with "drive" and phrase is "drive in"
                is_compound = True
                break
        if is_compound:
            continue

        # This is a valid "in" — extract the place
        place_candidate = after_in.strip()

        # Strip trailing punctuation
        place_candidate = place_candidate.rstrip(".,!?;:")

        if not place_candidate:
            return text, None

        # Check if before_in is meaningful (not just filler words)
        before_stripped = _strip_filler(before_in).strip()
        if not before_stripped:
            return text, None

        return before_in.strip(), place_candidate

    return text, None


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

    # --- Rule 2b: "in <place>" extraction ---
    place_name = None
    before_text, place_candidate = _extract_place(spatial_keywords_removed)

    if place_candidate is not None:
        place_name = place_candidate
        # Use before_text for category lookup
        category_text = _strip_filler(before_text).strip()
        entry, search_text = _lookup_category(category_text)

        if original_intent == "route_corridor":
            # Corridor + city = city_corridor
            original_intent = "city_corridor"
            if has_route:
                intent = "city_corridor"
            else:
                intent = "city_proximity"
                fallback_reason = "no_route"
        else:
            intent = "city_proximity"
            original_intent = "city_proximity"
    else:
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
        "nominatim_queries": entry.get("nominatim_query", [search_text]) if entry else [search_text],
        "osm_types": entry.get("osm_types") if entry else None,
        "osm_operator": entry.get("osm_operator") if entry else None,
        "radius_m": radius_m,
        "interval_m": interval_m,
        "place_name": place_name,
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
    route: Opt[list[list[float]]] = Field(None, max_length=50000)


@router.post("/spatial")
async def spatial_search(body: SpatialSearchBody):
    """Natural language spatial search endpoint."""
    # Deferred import to avoid circular dependency (main imports router from this file)
    from main import _query_nominatim, _query_poi, _query_osm_pois, _deduplicate, state

    parsed = parse_intent(
        body.query,
        has_position=body.position is not None,
        has_route=body.route is not None and len(body.route) >= 2,
    )

    search_text = parsed["search_text"]
    intent = parsed["intent"]

    # Geocode city intents
    place_name = parsed.get("place_name")
    geocode_result = None

    if place_name is not None:
        from geocode import geocode_place
        bias_lat = body.position.lat if body.position else None
        bias_lon = body.position.lon if body.position else None
        geocode_result = await geocode_place(place_name, bias_lat, bias_lon)

        if geocode_result is None:
            return {
                "results": [],
                "intent": parsed["intent"],
                "original_intent": parsed["original_intent"],
                "fallback_reason": "geocode_failed",
                "category": parsed.get("category"),
                "place_name": place_name,
            }

    # Build bbox for spatial queries
    bbox = None
    if place_name is not None and geocode_result is not None:
        bbox = geocode_result["bbox"]
    elif intent == "route_corridor" and body.route:
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

    # Scale limit for corridor searches (need more candidates across a long route)
    if intent == "route_corridor" and body.route:
        route_len_km = distance_along_polyline(body.route) / 1000
        limit = min(200, max(50, int(route_len_km * 0.5)))
    else:
        limit = 30

    # Query Nominatim with each nominatim_query term in parallel, merge results.
    # For corridor searches, segment the bbox into tiles for even geographic coverage.
    nominatim_queries = parsed.get("nominatim_queries", [search_text])

    segment_bboxes = [bbox] if bbox else [None]
    if intent == "route_corridor" and body.route and len(body.route) >= 2:
        # Split route into ~100 km segments with independent bboxes
        lngs = [p[0] for p in body.route]
        lats = [p[1] for p in body.route]
        lng_range = max(lngs) - min(lngs)
        n_segments = max(1, int(lng_range / 1.0))  # ~1 degree ≈ 90-110 km
        segment_bboxes = []
        for i in range(n_segments):
            seg_lng_min = min(lngs) + (lng_range * i / n_segments) - 0.02
            seg_lng_max = min(lngs) + (lng_range * (i + 1) / n_segments) + 0.02
            segment_bboxes.append(
                f"{seg_lng_min},{min(lats) - 0.02},{seg_lng_max},{max(lats) + 0.02}"
            )

    nom_tasks = []
    for seg_bbox in segment_bboxes:
        for q in nominatim_queries:
            nom_tasks.append(_query_nominatim(q, limit, seg_bbox))
    poi_task = _query_poi(search_text, limit, bbox)

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

    if osm_poi_task:
        all_results = await asyncio.gather(*nom_tasks, poi_task, osm_poi_task, return_exceptions=True)
        osm_poi_results = all_results[-1] if not isinstance(all_results[-1], BaseException) else []
        poi_results = all_results[-2] if not isinstance(all_results[-2], BaseException) else []
    else:
        all_results = await asyncio.gather(*nom_tasks, poi_task, return_exceptions=True)
        osm_poi_results = []
        poi_results = all_results[-1] if not isinstance(all_results[-1], BaseException) else []

    # Merge all Nominatim results (deduplicate by lat/lon proximity)
    nom_results = []
    seen_coords: set[tuple[float, float]] = set()
    nom_end_idx = len(all_results) - (2 if osm_poi_task else 1)
    for result in all_results[:nom_end_idx]:
        if isinstance(result, BaseException):
            continue
        for r in result:
            key = (round(float(r.get("lat", 0)), 4), round(float(r.get("lon", 0)), 4))
            if key not in seen_coords:
                seen_coords.add(key)
                nom_results.append(r)

    # Boost GNIS class matches when a class is specified
    gnis_class = parsed.get("gnis_class")
    if gnis_class and poi_results:
        class_matches = [r for r in poi_results if (r.get("class") or "").lower() == gnis_class.lower()]
        others = [r for r in poi_results if (r.get("class") or "").lower() != gnis_class.lower()]
        poi_results = class_matches + others

    merged = _deduplicate(nom_results, poi_results, osm_poi_results if osm_poi_results else None)

    # Post-filter by OSM type when a known category was matched.
    # This removes false positives like "Gas Pipeline Road" from gas station searches.
    osm_types = parsed.get("osm_types")
    if osm_types and merged:
        filtered = []
        for r in merged:
            osm_cat = r.get("osm_category", "")
            osm_typ = r.get("osm_type", "")
            if (osm_cat, osm_typ) in osm_types:
                filtered.append(r)
            elif r.get("type") == "poi":
                # POI database results don't have osm_category -- keep them
                filtered.append(r)
            elif r.get("type") == "osm_poi":
                # OSM POI results already filtered by osm_key/osm_value -- keep them
                filtered.append(r)
        # If filtering removed everything, fall back to unfiltered
        # (better to show noisy results than nothing)
        if filtered:
            merged = filtered

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
    if intent == "city_corridor" and body.route:
        merged = corridor_filter(body.route, merged, corridor_width_m=CORRIDOR_WIDTH_M, interval_m=parsed.get("interval_m"))
        if not merged:
            return {
                "results": [],
                "intent": intent,
                "original_intent": parsed["original_intent"],
                "fallback_reason": "city_not_on_route",
                "category": parsed.get("category"),
                "place_name": place_name,
            }
        # Compute distance_m from geocoded city center (not GPS)
        if geocode_result:
            city_lat = geocode_result["lat"]
            city_lon = geocode_result["lon"]
            for r in merged:
                try:
                    r["distance_m"] = round(haversine_m(city_lat, city_lon, float(r["lat"]), float(r["lon"])), 1)
                except (KeyError, TypeError, ValueError):
                    r["distance_m"] = None
    elif intent == "city_proximity" and geocode_result:
        city_lat = geocode_result["lat"]
        city_lon = geocode_result["lon"]
        for r in merged:
            try:
                r["distance_m"] = round(haversine_m(city_lat, city_lon, float(r["lat"]), float(r["lon"])), 1)
            except (KeyError, TypeError, ValueError):
                r["distance_m"] = None
        merged.sort(key=lambda r: r.get("distance_m") or float("inf"))
    elif intent == "route_corridor" and body.route:
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

    # Corridor results need more entries to cover the route length.
    # Even without an explicit "every N miles" request, apply a minimum
    # spacing to avoid clustering all results at the route start.
    if intent == "route_corridor" and not parsed.get("interval_m") and len(merged) > 10:
        # Auto-space: select up to 20 results with minimum ~30 km spacing
        spaced = [merged[0]]
        for r in merged[1:]:
            last_dist = spaced[-1].get("distance_along_route_m", 0)
            this_dist = r.get("distance_along_route_m", 0)
            if this_dist - last_dist >= 30_000:  # 30 km minimum gap
                spaced.append(r)
        merged = spaced

    max_results = 20 if intent == "route_corridor" else 10

    return {
        "results": merged[:max_results],
        "intent": parsed["intent"],
        "original_intent": parsed["original_intent"],
        "fallback_reason": parsed.get("fallback_reason"),
        "category": parsed.get("category"),
        "place_name": place_name,
    }
