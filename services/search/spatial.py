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
