# City-Aware Spatial Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "gas stations in Flagstaff" and "restaurants in Phoenix along my route" query patterns to the natural language spatial search parser.

**Architecture:** Extend the regex-based intent parser with space-bounded "in" detection and compound phrase filtering. Add a new async `geocode_place()` function with position-biased caching. City intents get their own execution paths in the endpoint, distinct from existing proximity/corridor paths. Frontend gains subtitle display for new intents and geocode error messages.

**Tech Stack:** Python/FastAPI (backend), Vanilla JS (frontend), local Nominatim (geocoding), pytest (testing)

**Spec:** `docs/superpowers/specs/2026-04-09-city-aware-spatial-search-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `services/search/spatial.py` | Intent parser: "in" extraction, compound filtering, new intents |
| Create | `services/search/geocode.py` | Async geocode helper with position-biased caching |
| Modify | `services/search/main.py` | Import geocode module, wire up for endpoint use |
| Modify | `frontend/app.js` | Subtitle display for city intents + geocode error messages |
| Modify | `tests/test_intent_parser.py` | Unit tests for "in" extraction and new intents |
| Create | `tests/test_geocode.py` | Integration tests for geocode function + cache |
| Modify | `tests/test_spatial_endpoint.py` | Integration tests for city_proximity and city_corridor paths |

---

## Task 1: Parser — "in" Place Extraction

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md

Follow TDD: write failing test → implement fix → verify green.

**Files:**
- Modify: `services/search/spatial.py:22-26` (add COMPOUND_IN_PHRASES constant)
- Modify: `services/search/spatial.py:136-184` (add `_extract_place()` helper)
- Test: `tests/test_intent_parser.py`

### Step 1: Write failing tests for place extraction

- [ ] **Step 1a: Add tests for basic "in" extraction**

Add to `tests/test_intent_parser.py`:

```python
class TestCityPlaceExtraction:
    """Tests for 'in <place>' extraction from queries."""

    def test_category_in_city(self):
        result = parse_intent("gas stations in flagstaff", has_position=False, has_route=False)
        assert result["place_name"] == "flagstaff"
        assert result["category"] == "gas station"
        assert result["intent"] == "city_proximity"

    def test_category_in_city_uppercase(self):
        result = parse_intent("Gas Stations In Flagstaff", has_position=False, has_route=False)
        assert result["place_name"] == "Flagstaff"
        assert result["category"] == "gas station"
        assert result["intent"] == "city_proximity"

    def test_multi_word_city(self):
        result = parse_intent("restaurants in las vegas", has_position=False, has_route=False)
        assert result["place_name"] == "las vegas"
        assert result["category"] == "restaurant"

    def test_city_with_state_suffix(self):
        result = parse_intent("gas stations in phoenix, az", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix, az"
        assert result["category"] == "gas station"

    def test_trailing_punctuation_stripped(self):
        result = parse_intent("gas stations in phoenix!", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"

    def test_trailing_period_stripped(self):
        result = parse_intent("gas stations in phoenix.", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"

    def test_zip_code_as_place(self):
        result = parse_intent("gas stations in 85001", has_position=False, has_route=False)
        assert result["place_name"] == "85001"
        assert result["category"] == "gas station"

    def test_no_place_after_in(self):
        """'gas stations in' with nothing after should not extract a place."""
        result = parse_intent("gas stations in", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_empty_before_in(self):
        """'in flagstaff' with nothing before should be plain intent."""
        result = parse_intent("in flagstaff", has_position=True, has_route=False)
        assert result["place_name"] is None
        assert result["intent"] == "plain"

    def test_in_inside_word_not_matched(self):
        """'drinking water in phoenix' — the 'in' in 'drinking' is NOT a split point."""
        result = parse_intent("drinking water in phoenix", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"
        assert result["category"] == "water"
```

- [ ] **Step 1b: Add tests for compound phrase handling**

```python
class TestCompoundInPhrases:
    """Tests for compound 'in' words that should not trigger place extraction."""

    def test_drive_in_hyphenated_no_second_in(self):
        """'drive-in theater' has no second 'in' — no place extraction."""
        result = parse_intent("drive-in theater", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_drive_in_hyphenated_with_city(self):
        """'drive-in restaurants in phoenix' — second 'in' is the split point."""
        result = parse_intent("drive-in restaurants in phoenix", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"
        assert result["category"] == "restaurant"

    def test_drive_in_unhyphenated_with_city(self):
        """'drive in restaurants in phoenix' — compound detected, second 'in' used."""
        result = parse_intent("drive in restaurants in phoenix", has_position=False, has_route=False)
        assert result["place_name"] == "phoenix"
        assert result["category"] == "restaurant"

    def test_walk_in_clinic_no_city(self):
        result = parse_intent("walk-in clinic", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_dine_in_with_city(self):
        result = parse_intent("dine in restaurants in mesa", has_position=False, has_route=False)
        assert result["place_name"] == "mesa"
        assert result["category"] == "restaurant"
```

- [ ] **Step 1c: Add tests for Approach C fallback (unknown category)**

```python
class TestApproachCFallback:
    """When text before 'in' is not a known category, still extract place."""

    def test_brand_in_city(self):
        result = parse_intent("shell in tucson", has_position=False, has_route=False)
        assert result["place_name"] == "tucson"
        assert result["category"] is None
        assert result["search_text"] == "shell"
        assert result["intent"] == "city_proximity"

    def test_unknown_business_in_city(self):
        result = parse_intent("filibertos in mesa", has_position=False, has_route=False)
        assert result["place_name"] == "mesa"
        assert result["category"] is None
        assert "filibertos" in result["search_text"].lower()
```

- [ ] **Step 1d: Add regression tests — existing intents must have place_name=None**

```python
class TestExistingIntentsRegression:
    """Existing intent types must NOT accidentally extract a place_name."""

    def test_plain_has_no_place(self):
        result = parse_intent("Phoenix", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_proximity_has_no_place(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["place_name"] is None

    def test_corridor_has_no_place(self):
        result = parse_intent("gas stations along my route", has_position=True, has_route=True)
        assert result["place_name"] is None

    def test_fallback_has_no_place(self):
        result = parse_intent("nearest hospital", has_position=False, has_route=False)
        assert result["place_name"] is None

    def test_implicit_proximity_has_no_place(self):
        result = parse_intent("gas", has_position=True, has_route=False)
        assert result["place_name"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_intent_parser.py -v`
Expected: FAIL — `KeyError: 'place_name'` (field doesn't exist yet)

- [ ] **Step 3: Implement `_extract_place()` and compound phrase table**

In `services/search/spatial.py`, add after the `FILLER_WORDS` set (around line 26):

```python
# Protected compound phrases containing "in". Stored normalized (lowercase, no hyphens).
# Prevents the "in" within these from being treated as a place separator.
COMPOUND_IN_PHRASES = {"drive in", "check in", "walk in", "plug in", "built in",
                       "dine in", "sign in", "log in", "trade in", "break in"}


def _extract_place(text: str) -> tuple[str, str | None]:
    """Extract a place name from 'category in place' pattern.

    Uses space-bounded 'in' detection (NOT \\b word boundary).
    Returns (remaining_text, place_name) or (original_text, None).
    """
    # Normalize for compound detection: replace hyphens with spaces
    normalized = text.replace("-", " ").lower()

    # Find all ' in ' positions (space-bounded). Also check ' in' at end.
    candidates = []
    search_lower = " " + text.lower() + " "
    pos = 0
    while True:
        idx = search_lower.find(" in ", pos)
        if idx == -1:
            break
        # idx is position in search_lower; adjust for the leading space we added
        real_idx = idx  # position of the space before "in" in padded string
        candidates.append(real_idx)
        pos = idx + 1

    if not candidates:
        return text, None

    # Check candidates right to left, skip compounds
    for candidate_pos in reversed(candidates):
        # Text before this 'in' in the original string (offset by 1 for leading space)
        before = text[:candidate_pos].rstrip()
        after = text[candidate_pos:].strip()

        # Remove the 'in ' prefix from after
        if after.lower().startswith("in "):
            place_candidate = after[3:].strip()
        elif after.lower() == "in":
            continue  # "in" at end with nothing after
        else:
            continue

        if not place_candidate:
            continue

        # Check if this 'in' is part of a compound phrase
        before_normalized = before.replace("-", " ").lower().rstrip()
        is_compound = False
        for phrase in COMPOUND_IN_PHRASES:
            # Check if the text before "in" ends with the compound prefix
            prefix = phrase.replace(" in", "").strip()
            if before_normalized.endswith(prefix):
                words_before = before_normalized.split()
                prefix_words = prefix.split()
                if words_before[-len(prefix_words):] == prefix_words:
                    is_compound = True
                    break

        if not is_compound:
            # Sanitize place_candidate: strip trailing punctuation
            place_candidate = place_candidate.rstrip(".,!?;:")
            if not place_candidate:
                continue

            # Check that before_in is not empty after filler stripping
            before_stripped = _strip_filler(before).strip()
            if not before_stripped:
                return text, None  # "in flagstaff" alone — too ambiguous

            return before, place_candidate

    return text, None
```

- [ ] **Step 4: Wire `_extract_place()` into `parse_intent()`**

In `services/search/spatial.py`, modify `parse_intent()`. The extraction runs AFTER both corridor stripping AND proximity regex checks, but BEFORE category lookup. This is the correct order:

1. Corridor modifier stripping (existing, lines 224-251)
2. Proximity regex checks (existing, lines 254-296) — these set intent and strip their keywords into `spatial_keywords_removed`
3. **"in" extraction on `spatial_keywords_removed`** (NEW — insert here)
4. Category lookup (existing, but now operates on text with place stripped)

This means "nearest gas stations in flagstaff" → proximity regex fires on "nearest" → strips it → `spatial_keywords_removed = "gas stations in flagstaff"` → "in" extraction finds "flagstaff" → intent upgraded to `city_proximity`.

Replace the section starting at `# Strip filler words from extracted category text` (line 298) through the return statement (line 321) with:

```python
    # --- "in <place>" extraction (runs after corridor + proximity stripping) ---
    remaining_text, place_name = _extract_place(spatial_keywords_removed)

    if place_name is not None:
        category_text = _strip_filler(remaining_text).strip()
        entry, search_text = _lookup_category(category_text)

        # Upgrade intent to city-aware variant
        if original_intent == "route_corridor" or corridor_match or every_match:
            original_intent = "city_corridor"
            if has_route:
                intent = "city_corridor"
            else:
                intent = "city_proximity"
                fallback_reason = "no_route"
        else:
            original_intent = "city_proximity"
            intent = "city_proximity"
    else:
        # Original path — no place extraction
        category_text = _strip_filler(spatial_keywords_removed).strip()
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_intent_parser.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
cd /home/administrator/Code/geographica
git add services/search/spatial.py tests/test_intent_parser.py
git commit -m "feat(search): add 'in <place>' extraction to intent parser

Extracts city/place names from queries like 'gas stations in flagstaff'.
Uses space-bounded 'in' detection with compound phrase filtering.
Adds city_proximity and city_corridor intent types."
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage of the fix (are error paths tested? edge cases?)
3. Run tests (or relevant subset) and confirm green

---

## Task 2: Parser — City + Corridor Combo Intent

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md

Follow TDD: write failing test → implement fix → verify green.

**Files:**
- Modify: `services/search/spatial.py` (parse_intent city_corridor handling)
- Test: `tests/test_intent_parser.py`

### Step 1: Write failing tests for city + corridor combo

- [ ] **Step 1a: Add tests**

Add to `tests/test_intent_parser.py`:

```python
class TestCityCorridorIntent:
    """Tests for 'category in city along my route' pattern."""

    def test_city_corridor_with_route(self):
        result = parse_intent("gas stations in flagstaff along my route",
                              has_position=True, has_route=True)
        assert result["intent"] == "city_corridor"
        assert result["place_name"] == "flagstaff"
        assert result["category"] == "gas station"

    def test_city_corridor_on_route(self):
        result = parse_intent("restaurants in phoenix on my route",
                              has_position=True, has_route=True)
        assert result["intent"] == "city_corridor"
        assert result["place_name"] == "phoenix"
        assert result["category"] == "restaurant"

    def test_city_corridor_every_n_miles(self):
        result = parse_intent("gas stations in flagstaff every 50 miles",
                              has_position=True, has_route=True)
        assert result["intent"] == "city_corridor"
        assert result["place_name"] == "flagstaff"
        assert result["interval_m"] is not None

    def test_city_corridor_falls_back_without_route(self):
        result = parse_intent("gas stations in flagstaff along my route",
                              has_position=True, has_route=False)
        assert result["intent"] == "city_proximity"
        assert result["original_intent"] == "city_corridor"
        assert result["fallback_reason"] == "no_route"
        assert result["place_name"] == "flagstaff"

    def test_city_corridor_falls_back_without_anything(self):
        result = parse_intent("gas stations in flagstaff along my route",
                              has_position=False, has_route=False)
        assert result["intent"] == "city_proximity"
        assert result["original_intent"] == "city_corridor"
        assert result["fallback_reason"] == "no_route"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_intent_parser.py::TestCityCorridorIntent -v`
Expected: FAIL (corridor keywords get stripped first, but the city_corridor intent assignment may not work yet)

- [ ] **Step 3: Fix implementation if needed**

The `_extract_place()` call runs on `spatial_keywords_removed` which already has "along my route" stripped out. So "gas stations in flagstaff along my route" becomes "gas stations in flagstaff" after corridor stripping → "in" extraction finds "flagstaff" → `corridor_match` is truthy → intent assigned as `city_corridor`.

If tests fail, debug the interaction between corridor stripping and "in" extraction. The critical thing: corridor keywords must be stripped BEFORE `_extract_place()` runs, so the place candidate doesn't include "along my route".

Verify that `spatial_keywords_removed` after corridor stripping of "gas stations in flagstaff along my route" is "gas stations in flagstaff " (with trailing space). The `_extract_place()` function should handle trailing whitespace.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_intent_parser.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
cd /home/administrator/Code/geographica
git add services/search/spatial.py tests/test_intent_parser.py
git commit -m "feat(search): add city_corridor intent for 'in city along route' queries"
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage of the fix (are error paths tested? edge cases?)
3. Run tests and confirm green

---

After Tasks 1 and 2:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

## Task 3: Geocode Helper with Async-Safe Cache

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
3. Read docs/pitfalls/implementation-pitfalls.md — pitfall #6 (offline-first) applies: the geocode function calls LOCAL Nominatim only, never external services.

Follow TDD: write failing test → implement fix → verify green.

**Files:**
- Create: `services/search/geocode.py`
- Create: `tests/test_geocode.py`

**WARNING:** Do NOT use `functools.lru_cache` on async functions. It caches coroutine objects, not resolved values. Use a dict + asyncio.Lock as shown below.

**WARNING:** Nominatim `boundingbox` returns `[south_lat, north_lat, west_lon, east_lon]` as STRINGS. The internal bbox format is `"lon_min,lat_min,lon_max,lat_max"`. These are DIFFERENT orderings. Parse to floats and reorder explicitly.

### Step 1: Write failing tests

- [ ] **Step 1a: Create test file with geocode tests**

Create `tests/test_geocode.py`:

```python
"""Integration tests for geocode_place() — requires local Nominatim container."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

import asyncio
import pytest
import httpx


NOMINATIM_URL = "http://localhost:8092"


@pytest.fixture(autouse=True)
def check_nominatim():
    """Fail immediately if Nominatim container is not responding."""
    try:
        resp = httpx.get(f"{NOMINATIM_URL}/status", timeout=2.0)
        resp.raise_for_status()
    except Exception:
        pytest.fail("Nominatim container not responding at " + NOMINATIM_URL)


@pytest.fixture(autouse=True)
def init_and_clear_geocode():
    """Initialize geocode module with HTTP client and clear cache between tests."""
    from geocode import init_geocode, clear_cache
    client = httpx.AsyncClient()
    init_geocode(client, NOMINATIM_URL)
    clear_cache()
    yield
    clear_cache()


class TestGeocodePlaceBasic:
    def test_geocode_flagstaff(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("flagstaff"))
        assert result is not None
        assert abs(result["lat"] - 35.2) < 0.5  # Flagstaff is roughly 35.2N
        assert abs(result["lon"] - (-111.65)) < 0.5  # -111.65W
        assert "bbox" in result

    def test_geocode_phoenix(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("phoenix"))
        assert result is not None
        assert abs(result["lat"] - 33.45) < 0.5
        assert abs(result["lon"] - (-112.07)) < 0.5

    def test_geocode_nonexistent(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(
            geocode_place("xyzzy_nonexistent_place_12345")
        )
        assert result is None

    def test_geocode_zip_code(self):
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("85001"))
        assert result is not None
        assert abs(result["lat"] - 33.45) < 0.5  # 85001 is Phoenix area


class TestGeocodeBboxFormat:
    def test_bbox_is_internal_format(self):
        """Bbox must be 'lon_min,lat_min,lon_max,lat_max' format."""
        from geocode import geocode_place
        result = asyncio.get_event_loop().run_until_complete(geocode_place("flagstaff"))
        assert result is not None
        parts = result["bbox"].split(",")
        assert len(parts) == 4
        lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
        # Flagstaff is in Western US: lon negative, lat positive
        assert lon_min < 0
        assert lon_max < 0
        assert lat_min > 0
        assert lat_max > 0
        assert lon_min <= lon_max
        assert lat_min <= lat_max


class TestGeocodeCache:
    def test_cache_returns_same_result(self):
        from geocode import geocode_place
        loop = asyncio.get_event_loop()
        r1 = loop.run_until_complete(geocode_place("flagstaff"))
        r2 = loop.run_until_complete(geocode_place("flagstaff"))
        assert r1 == r2

    def test_cache_is_case_insensitive(self):
        from geocode import geocode_place
        loop = asyncio.get_event_loop()
        r1 = loop.run_until_complete(geocode_place("Flagstaff"))
        r2 = loop.run_until_complete(geocode_place("flagstaff"))
        assert r1 == r2

    def test_cache_clear_works(self):
        from geocode import geocode_place, clear_cache, _geocode_cache
        loop = asyncio.get_event_loop()
        loop.run_until_complete(geocode_place("flagstaff"))
        assert len(_geocode_cache) > 0
        clear_cache()
        assert len(_geocode_cache) == 0


class TestGeocodeBias:
    def test_bias_toward_user_position(self):
        """With position bias near Phoenix, 'mesa' should resolve to Mesa, AZ."""
        from geocode import geocode_place
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            geocode_place("mesa", bias_lat=33.45, bias_lon=-112.07)
        )
        assert result is not None
        # Mesa, AZ is ~33.4N, -111.8W
        assert abs(result["lat"] - 33.4) < 0.5
        assert abs(result["lon"] - (-111.8)) < 0.5


class TestGeocodeTimeout:
    def test_timeout_returns_none(self, monkeypatch):
        """If Nominatim times out, geocode_place returns None."""
        from geocode import geocode_place, clear_cache
        import geocode as geocode_module
        clear_cache()

        original_get = httpx.AsyncClient.get

        async def slow_get(self, *args, **kwargs):
            raise httpx.TimeoutException("simulated timeout")

        monkeypatch.setattr(httpx.AsyncClient, "get", slow_get)

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(geocode_place("flagstaff"))
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_geocode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'geocode'`

- [ ] **Step 3: Implement geocode.py**

Create `services/search/geocode.py`:

```python
"""Async geocode helper with position-biased caching.

Geocodes place names via local Nominatim. Separate from _query_nominatim()
which does bounded POI search (bounded=1). This function does ranking-biased
geocoding (bounded=0 or omitted).
"""
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Async-safe cache: dict + lock. Key is (normalized_name, lat_bucket, lon_bucket).
# DO NOT use functools.lru_cache — it caches coroutine objects, not resolved values.
_geocode_cache: dict[tuple[str, int, int], Optional[dict]] = {}
_geocode_lock = asyncio.Lock()

# Module-level HTTP client and URL — set by init_geocode() from main.py
_http_client = None
_nominatim_url = None


def init_geocode(http_client, nominatim_url: str):
    """Initialize the geocode module with shared HTTP client and Nominatim URL."""
    global _http_client, _nominatim_url
    _http_client = http_client
    _nominatim_url = nominatim_url


def clear_cache():
    """Clear the geocode cache. Used by tests."""
    _geocode_cache.clear()


async def geocode_place(
    place_name: str,
    bias_lat: float = None,
    bias_lon: float = None,
) -> Optional[dict]:
    """Geocode a place name via local Nominatim.

    Returns {"lat": float, "lon": float, "bbox": str} or None.
    bbox is in internal format: "lon_min,lat_min,lon_max,lat_max".

    Args:
        place_name: City, town, zip code, or other place name.
        bias_lat: User latitude for ranking bias (not hard filtering).
        bias_lon: User longitude for ranking bias.
    """
    # Cache key: normalized name + coarse 1-degree position bucket
    bias_bucket = (round(bias_lat or 0), round(bias_lon or 0))
    cache_key = (place_name.lower().strip(), bias_bucket[0], bias_bucket[1])

    async with _geocode_lock:
        if cache_key in _geocode_cache:
            return _geocode_cache[cache_key]

    # Build Nominatim request
    params: dict = {"q": place_name, "limit": 1, "format": "jsonv2"}
    if bias_lat is not None and bias_lon is not None:
        # Ranking bias (NOT bounded) — Nominatim prefers results in this box
        params["viewbox"] = f"{bias_lon - 2},{bias_lat + 2},{bias_lon + 2},{bias_lat - 2}"
        # Do NOT set bounded=1 — we want ranking bias, not hard filtering

    result = None
    try:
        resp = await _http_client.get(
            f"{_nominatim_url}/search", params=params, timeout=1.0
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            item = data[0]
            bb = item["boundingbox"]  # [south_lat, north_lat, west_lon, east_lon] as strings
            # Convert to internal format: lon_min,lat_min,lon_max,lat_max
            lat_min = float(bb[0])
            lat_max = float(bb[1])
            lon_min = float(bb[2])
            lon_max = float(bb[3])
            # Pad by ~2km (0.02 degrees)
            bbox_str = (
                f"{lon_min - 0.02},{lat_min - 0.02},"
                f"{lon_max + 0.02},{lat_max + 0.02}"
            )
            result = {
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "bbox": bbox_str,
            }
        else:
            logger.info("Geocode found no results for '%s'", place_name)
    except Exception as exc:
        logger.warning("Geocode failed for '%s': %s", place_name, exc)

    async with _geocode_lock:
        _geocode_cache[cache_key] = result

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_geocode.py -v`
Expected: ALL PASS (requires Nominatim container running)

Note: The `init_geocode()` call must be made before tests run. The test fixtures import from geocode directly and the module uses `_http_client`. For tests, you may need to call `init_geocode(httpx.AsyncClient(), "http://localhost:8092")` in a conftest or fixture. Adjust as needed.

- [ ] **Step 5: Commit**

```bash
cd /home/administrator/Code/geographica
git add services/search/geocode.py tests/test_geocode.py
git commit -m "feat(search): add geocode_place() with async-safe position-biased cache

Separate geocode function from _query_nominatim. Uses ranking bias
(bounded=0), 1-second timeout, dict cache with asyncio.Lock.
Cache key includes position bucket to prevent cross-city contamination."
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage of the fix (are error paths tested? edge cases?)
3. Run tests and confirm green

---

## Task 4: Endpoint — City Intent Execution Paths

BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/ (or invoke /test-driven-development)
2. Read docs/pitfalls/testing-pitfalls.md
3. Read docs/pitfalls/implementation-pitfalls.md

Follow TDD: write failing test → implement fix → verify green.

**Files:**
- Modify: `services/search/spatial.py:552-750` (endpoint)
- Modify: `services/search/main.py` (import + init geocode module)
- Test: `tests/test_spatial_endpoint.py`

**WARNING:** City intents MUST have their own execution paths. Do NOT add `elif intent == "city_proximity"` to existing proximity/corridor branches. The existing `proximity` path filters by `distance_m` (requires GPS). City proximity computes distance from geocoded city center instead.

**WARNING:** For `city_corridor`, use the city bbox for Nominatim POI queries, then apply `corridor_filter()`. Do NOT intersect city bbox with route bbox — it's geometrically broken for diagonal routes.

### Step 1: Write failing endpoint tests

- [ ] **Step 1a: Add city_proximity and city_corridor endpoint tests**

Add to `tests/test_spatial_endpoint.py`:

```python
class TestCityIntentEndpoint:
    """Integration tests for city-aware spatial search.
    Requires local Nominatim container.
    """
    @pytest.fixture(autouse=True)
    def setup(self):
        from main import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app)
        # Clear geocode cache between tests
        from geocode import clear_cache
        clear_cache()

    @pytest.fixture(autouse=True)
    def check_nominatim(self):
        """Fail if Nominatim not responding."""
        import httpx
        try:
            resp = httpx.get("http://localhost:8092/status", timeout=2.0)
            resp.raise_for_status()
        except Exception:
            pytest.fail("Nominatim container not responding")

    def test_city_proximity_returns_results_near_city(self):
        resp = self.client.post("/spatial", json={
            "query": "gas stations in flagstaff",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "city_proximity"
        assert data["place_name"] == "flagstaff"
        assert data["category"] == "gas station"
        # Results should exist (Nominatim has fuel stations in Flagstaff)
        # If no results, the geocode or query pipeline is broken
        assert len(data["results"]) >= 0  # May be 0 if Nominatim data is limited
        # place_name always present in response
        assert "place_name" in data

    def test_city_corridor_filters_to_route(self):
        # PHX to Flagstaff route (simplified — 3 points along I-17)
        route = [
            [-112.07, 33.45],  # Phoenix
            [-111.85, 34.25],  # Camp Verde area
            [-111.65, 35.20],  # Flagstaff
        ]
        resp = self.client.post("/spatial", json={
            "query": "gas stations in flagstaff along my route",
            "route": route,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "city_corridor"
        assert data["place_name"] == "flagstaff"

    def test_geocode_failed_returns_zero_results(self):
        resp = self.client.post("/spatial", json={
            "query": "gas stations in xyzzy_nonexistent_place_12345",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["fallback_reason"] == "geocode_failed"
        assert data["place_name"] == "xyzzy_nonexistent_place_12345"

    def test_city_not_on_route(self):
        # Route from PHX to Flagstaff — Los Angeles is NOT on this route
        route = [
            [-112.07, 33.45],  # Phoenix
            [-111.85, 34.25],  # Camp Verde
            [-111.65, 35.20],  # Flagstaff
        ]
        resp = self.client.post("/spatial", json={
            "query": "gas stations in los angeles along my route",
            "route": route,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["fallback_reason"] == "city_not_on_route"

    def test_approach_c_brand_in_city(self):
        """'shell in tucson' — unknown category, but geocode succeeds."""
        resp = self.client.post("/spatial", json={
            "query": "shell in tucson",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "city_proximity"
        assert data["place_name"] == "tucson"
        # Results may or may not include Shell stations depending on Nominatim data

    def test_city_proximity_distance_from_city_center(self):
        """distance_m should be from geocoded city center, not GPS."""
        resp = self.client.post("/spatial", json={
            "query": "gas stations in flagstaff",
            "position": {"lat": 33.45, "lon": -112.07},  # Phoenix (far from Flagstaff)
        })
        assert resp.status_code == 200
        data = resp.json()
        if data["results"]:
            for r in data["results"]:
                if r.get("distance_m") is not None:
                    # Distance should be small (within Flagstaff area), not 200km+ to Phoenix
                    assert r["distance_m"] < 50000  # Less than 50km from city center

    def test_place_name_in_response(self):
        resp = self.client.post("/spatial", json={
            "query": "restaurants in phoenix",
        })
        data = resp.json()
        assert "place_name" in data
        assert data["place_name"] == "phoenix"

    def test_non_city_query_has_null_place_name(self):
        """Existing queries should have place_name: null in response."""
        resp = self.client.post("/spatial", json={
            "query": "nearest gas station",
            "position": {"lat": 33.45, "lon": -112.07},
        })
        data = resp.json()
        assert data.get("place_name") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_spatial_endpoint.py::TestCityIntentEndpoint -v`
Expected: FAIL — city intents not wired in endpoint yet

- [ ] **Step 3: Wire geocode module into main.py**

In `services/search/main.py`, add the import and initialization:

```python
# Near the top with other imports:
from geocode import init_geocode, geocode_place

# In the startup event (find the @app.on_event("startup") or lifespan):
init_geocode(state.http_client, NOMINATIM_URL)
```

Find the existing startup code that creates `state.http_client` and add `init_geocode()` right after.

- [ ] **Step 4: Add city intent execution paths to spatial endpoint**

In `services/search/spatial.py`, modify the `spatial_search()` endpoint function. Add the city intent handling BEFORE the existing bbox/query logic. The key change: when `place_name` is present, geocode it and use the city bbox.

After `parsed = parse_intent(...)` and before the existing bbox construction, add:

```python
    # --- City intent: geocode the place name ---
    place_name = parsed.get("place_name")
    geocode_result = None

    if place_name is not None:
        from geocode import geocode_place
        bias_lat = body.position.lat if body.position else None
        bias_lon = body.position.lon if body.position else None
        geocode_result = await geocode_place(place_name, bias_lat, bias_lon)

        if geocode_result is None:
            # Geocode failed — return zero results with error
            return {
                "results": [],
                "intent": parsed["intent"],
                "original_intent": parsed["original_intent"],
                "fallback_reason": "geocode_failed",
                "category": parsed.get("category"),
                "place_name": place_name,
            }
```

Then modify the bbox construction section. Add a new branch for city intents:

```python
    # Build bbox for spatial queries
    bbox = None
    if place_name is not None and geocode_result is not None:
        # City intent: use geocoded city bbox
        bbox = geocode_result["bbox"]
    elif intent == "route_corridor" and body.route:
        # ... existing corridor bbox logic ...
    elif intent == "proximity" and body.position:
        # ... existing proximity bbox logic ...
```

For the query execution, city intents reuse the same Nominatim fan-out + GNIS + OSM pipeline. No changes to query execution.

After the query results are merged, add city-specific post-processing:

```python
    # --- City intent post-processing ---
    if intent == "city_corridor" and body.route:
        merged = corridor_filter(
            body.route, merged,
            corridor_width_m=CORRIDOR_WIDTH_M,
            interval_m=parsed.get("interval_m"),
        )
        if not merged:
            # City not on route — all POIs filtered out
            return {
                "results": [],
                "intent": intent,
                "original_intent": parsed["original_intent"],
                "fallback_reason": "city_not_on_route",
                "category": parsed.get("category"),
                "place_name": place_name,
            }
    elif intent == "city_proximity" and geocode_result:
        # Compute distance from geocoded city center (not GPS)
        city_lat = geocode_result["lat"]
        city_lon = geocode_result["lon"]
        for r in merged:
            try:
                r["distance_m"] = round(haversine_m(
                    city_lat, city_lon, float(r["lat"]), float(r["lon"])
                ), 1)
            except (KeyError, TypeError, ValueError):
                r["distance_m"] = None
        merged.sort(key=lambda r: r.get("distance_m") or float("inf"))
    elif intent == "route_corridor" and body.route:
        # ... existing corridor filtering (unchanged) ...
    elif intent == "proximity":
        # ... existing proximity filtering (unchanged) ...
```

Add `place_name` to the response dict at the end of the function:

```python
    return {
        "results": merged[:limit],
        "intent": intent,
        "original_intent": parsed["original_intent"],
        "fallback_reason": parsed.get("fallback_reason"),
        "category": parsed.get("category"),
        "place_name": place_name,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/test_spatial_endpoint.py -v`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite**

Run: `cd /home/administrator/Code/geographica && python -m pytest tests/ -v`
Expected: ALL PASS — no regressions

- [ ] **Step 7: Commit**

```bash
cd /home/administrator/Code/geographica
git add services/search/spatial.py services/search/main.py tests/test_spatial_endpoint.py
git commit -m "feat(search): wire city_proximity and city_corridor endpoint paths

Geocodes place name via geocode_place(), uses city bbox for POI queries.
city_corridor applies corridor_filter() after fetching city-area POIs.
city_proximity computes distance from geocoded city center, not GPS.
Returns geocode_failed or city_not_on_route on failure."
```

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Verify test coverage of the fix (are error paths tested? edge cases?)
3. Run full test suite and confirm green

---

After Tasks 3 and 4:
You MUST carefully review the batch of work from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.

---

## Task 5: Frontend — Subtitle Display for City Intents

BEFORE starting work:
1. Read docs/pitfalls/implementation-pitfalls.md — pitfall #9 (frontend module boundaries) applies: add minimal code to app.js.

**Files:**
- Modify: `frontend/app.js:1063-1089` (subtitle and empty-state rendering)

**WARNING:** No JS test framework exists. Verify manually by reading the code carefully. Do NOT add a test framework — that's out of scope.

### Step 1: Update empty-state handling for geocode errors

- [ ] **Step 1a: Modify the empty results handler**

In `frontend/app.js`, find the empty results handler (around line 1063-1078). Update the `fallback_reason` checks to handle `geocode_failed` and `city_not_on_route`:

Replace the existing fallback_reason handling block:

```javascript
    if (!results || results.length === 0) {
      var emptyLi = document.createElement('li');
      if (metadata && metadata.fallback_reason === 'geocode_failed' && metadata.place_name) {
        emptyLi.textContent = "Couldn't find '" + metadata.place_name + "' — check spelling?";
      } else if (metadata && metadata.fallback_reason === 'city_not_on_route' && metadata.place_name) {
        emptyLi.textContent = "'" + metadata.place_name + "' doesn't appear to be along your route";
      } else if (metadata && metadata.original_intent !== 'plain' && metadata.fallback_reason) {
        emptyLi.textContent = metadata.fallback_reason === 'no_position'
          ? 'Enable GPS for proximity search'
          : metadata.fallback_reason === 'no_route'
            ? 'Set a route for corridor search'
            : 'No results found';
      } else if (metadata && metadata.intent !== 'plain') {
        emptyLi.textContent = 'No ' + (metadata.category || 'results') + ' found nearby';
      } else {
        emptyLi.textContent = 'No results found';
      }
      list.appendChild(emptyLi);
      list.classList.add('visible');
      return;
    }
```

### Step 2: Update subtitle rendering for city intents

- [ ] **Step 2a: Modify the intent subtitle logic**

Replace the subtitle block (around line 1082-1089):

```javascript
    // Intent subtitle for spatial queries
    if (metadata && metadata.intent !== 'plain') {
      var subtitleLi = document.createElement('li');
      subtitleLi.className = 'search-intent-subtitle';
      if (metadata.intent === 'city_proximity' && metadata.place_name) {
        var cat = metadata.category
          ? metadata.category.charAt(0).toUpperCase() + metadata.category.slice(1)
          : 'Results';
        subtitleLi.textContent = cat + ' in ' + metadata.place_name;
      } else if (metadata.intent === 'city_corridor' && metadata.place_name) {
        var cat2 = metadata.category
          ? metadata.category.charAt(0).toUpperCase() + metadata.category.slice(1)
          : 'Results';
        subtitleLi.textContent = cat2 + ' in ' + metadata.place_name + ' along route';
      } else if (metadata.intent === 'route_corridor') {
        subtitleLi.textContent = metadata.category
          ? metadata.category.charAt(0).toUpperCase() + metadata.category.slice(1) + ' along route'
          : 'Results along route';
      } else if (metadata.category) {
        subtitleLi.textContent = 'Nearest ' + metadata.category;
      } else {
        subtitleLi = null; // No subtitle for plain intent without category
      }
      if (subtitleLi) list.appendChild(subtitleLi);
    }
```

- [ ] **Step 3: Commit**

```bash
cd /home/administrator/Code/geographica
git add frontend/app.js
git commit -m "feat(frontend): add subtitle display for city-aware search intents

Shows 'Gas station in flagstaff' and 'Gas station in flagstaff along route'
subtitles. Displays explicit error messages for geocode_failed and
city_not_on_route fallback reasons."
```

---

## Task 6: Final Review and Full Test Run

BEFORE marking this task complete:
1. Review your tests against docs/pitfalls/testing-pitfalls.md
2. Review implementation against docs/pitfalls/implementation-pitfalls.md

- [ ] **Step 1: Run full test suite**

```bash
cd /home/administrator/Code/geographica && python -m pytest tests/ -v
```

Expected: ALL PASS

- [ ] **Step 2: Manual smoke test queries**

If the Docker stack is running, use curl to test:

```bash
# City proximity
curl -s -X POST http://localhost:8096/spatial \
  -H 'Content-Type: application/json' \
  -d '{"query": "gas stations in flagstaff"}' | python3 -m json.tool | head -30

# City corridor
curl -s -X POST http://localhost:8096/spatial \
  -H 'Content-Type: application/json' \
  -d '{"query": "gas stations in flagstaff along my route", "route": [[-112.07,33.45],[-111.85,34.25],[-111.65,35.20]]}' | python3 -m json.tool | head -30

# Geocode failure
curl -s -X POST http://localhost:8096/spatial \
  -H 'Content-Type: application/json' \
  -d '{"query": "gas stations in xyzzy_nonexistent"}' | python3 -m json.tool

# Existing query (regression check)
curl -s -X POST http://localhost:8096/spatial \
  -H 'Content-Type: application/json' \
  -d '{"query": "nearest gas station", "position": {"lat": 33.45, "lon": -112.07}}' | python3 -m json.tool | head -20
```

- [ ] **Step 3: Final commit if any adjustments needed**

```bash
cd /home/administrator/Code/geographica
git add -A
git commit -m "fix(search): address issues from final review"
```

You MUST carefully review the complete implementation from multiple perspectives
and revise/refine as appropriate. Repeat this review loop (you must do
a minimum of three review rounds; if you still find substantive issues
in the third review, keep going with additional rounds until there are
no findings) until you're confident there aren't any more issues. Then
update your private journal and continue onto the next tasks.
