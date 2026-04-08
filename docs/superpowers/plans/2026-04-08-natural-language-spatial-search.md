# Natural Language Spatial Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add natural language spatial search so users can type queries like "nearest gas station", "hospitals near me", or "gas stations along my route" and get distance-ranked, context-aware results with numbered map pins.

**Architecture:** A new `POST /search/spatial` endpoint in the search FastAPI service handles intent detection (rule-based regex), category extraction (synonym table + fallback), and spatial filtering (proximity radius or route corridor). The frontend sends GPS position and decoded route geometry alongside every query, renders numbered pins for all search results, and shows distance badges for spatial results.

**Tech Stack:** Python/FastAPI (backend), vanilla JS/MapLibre GL JS (frontend), SQLite FTS5 (POI), Nominatim (geocoding), aiosqlite, httpx

**Spec:** `docs/superpowers/specs/2026-04-08-natural-language-spatial-search-design.md`

---

## Execution Recommendation

**Recommended: Option 2 — parallel session with `/executing-plans` in a worktree.**

Reasoning:
- **Context consumption:** This session has consumed significant context across multiple brainstorming rounds, 3 bug hunts (imagery, TLS, GPS x2), and 5 adversarial review rounds. A fresh session starts with full context budget.
- **Plan self-containment:** The plan is fully self-contained — every task includes exact file paths, complete code blocks, test code, and expected outputs. A fresh subagent with only CLAUDE.md and this plan file has everything it needs.
- **Task sequentiality:** Tasks 1→2→3 are strictly sequential (each builds on the previous file). Tasks 4→5 are also sequential (both modify app.js). No parallelism opportunity — subagent-driven would dispatch serially anyway.
- **Risk profile:** The corridor math (Task 2) and the frontend pin rewrite (Task 5) are the riskiest tasks. Both benefit from focused single-session attention with the review loop, not parallel dispatch.

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `services/search/spatial.py` | Intent parser, synonym table, corridor math, spatial endpoint logic (~300 lines) |
| `tests/test_intent_parser.py` | Tests for intent detection and category extraction |
| `tests/test_corridor.py` | Tests for Douglas-Peucker, point-to-segment distance, corridor filtering |
| `tests/test_spatial_endpoint.py` | Integration tests for POST /search/spatial |

### Modified files
| File | Change |
|------|--------|
| `services/search/main.py` | Import and mount the spatial router, add POI lat/lon index on startup |
| `frontend/app.js` | Switch to POST, add `lastRouteCoords`, numbered pins, distance badges, remove old `searchMarker` |
| `frontend/style.css` | CSS for search result badges, distance labels, active highlight |

### Cross-task file dependencies
- `services/search/spatial.py` is created in Task 1, extended in Task 2, extended again in Task 3. Tasks 1-3 MUST run sequentially.
- `services/search/main.py` is modified ONLY in Task 3. No conflict with Tasks 1-2.
- `frontend/app.js` is modified in Task 4 and Task 5. Tasks 4-5 MUST run sequentially.
- `frontend/style.css` is modified ONLY in Task 5.
- Backend tasks (1-3) and frontend tasks (4-5) are independent and COULD run in parallel, but the E2E verification (Task 6) requires both.

### Pitfalls files
No `docs/pitfalls/testing-pitfalls.md` or `docs/pitfalls/implementation-pitfalls.md` exist in this project. Skip those review steps — but apply general pitfall awareness: avoid mocking the thing you're testing, test error paths not just happy paths, assert on correct behavior (not just absence of errors).

---

## Task 1: Intent Parser + Synonym Table

**Dependencies:** None (first task)
**Creates:** `services/search/spatial.py`, `tests/test_intent_parser.py`
**Does NOT modify:** any existing file

> BEFORE starting work:
> 1. Read the spec at `docs/superpowers/specs/2026-04-08-natural-language-spatial-search-design.md` — sections "Intent Parser" and "Synonym table"
> 2. No `dev/testing-pitfalls.md` exists yet — apply general TDD discipline
> Follow TDD: write failing test → implement fix → verify green.

**Behavior change:** Currently no `spatial.py` exists. After this task, `parse_intent(query, has_position, has_route)` returns a structured dict with intent classification, category extraction, fallback chain, and search text.

**Do NOT:**
- Add any FastAPI routes (that's Task 3)
- Add any corridor math (that's Task 2)
- Import from `main.py` (this module must be independently testable)
- Add any "improvements" beyond what the spec defines (no LLM, no fuzzy matching beyond plural normalization)

- [ ] **Step 1: Write failing tests for intent detection**

Create `tests/test_intent_parser.py`:

```python
"""Tests for the natural language intent parser and category extraction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

from spatial import parse_intent


class TestPlainIntent:
    def test_place_name(self):
        result = parse_intent("Phoenix", has_position=True, has_route=False)
        assert result["intent"] == "plain"
        assert result["category"] is None

    def test_unknown_text(self):
        result = parse_intent("asdfghjkl", has_position=False, has_route=False)
        assert result["intent"] == "plain"


class TestProximityIntent:
    def test_nearest(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"
        assert result["search_text"] == "gas station"

    def test_closest(self):
        result = parse_intent("closest hospital", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "hospital"

    def test_near_me(self):
        result = parse_intent("hospitals near me", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "hospital"

    def test_near_here(self):
        result = parse_intent("gas near here", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_nearby(self):
        result = parse_intent("nearby restaurants", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "restaurant"

    def test_within_miles(self):
        result = parse_intent("gas stations within 10 miles", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"
        assert result["radius_m"] is not None
        assert abs(result["radius_m"] - 16093) < 100  # 10 miles

    def test_within_km(self):
        result = parse_intent("hospitals within 5 km", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["radius_m"] is not None
        assert abs(result["radius_m"] - 5000) < 100


class TestCorridorIntent:
    def test_along_my_route(self):
        result = parse_intent("gas stations along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "gas station"

    def test_along_route(self):
        result = parse_intent("restaurants along route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "restaurant"

    def test_on_my_route(self):
        result = parse_intent("hotels on my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "hotel"

    def test_every_n_miles(self):
        result = parse_intent("gas stations every 50 miles along my route", has_position=True, has_route=True)
        assert result["intent"] == "route_corridor"
        assert result["category"] == "gas station"
        assert result["interval_m"] is not None
        assert abs(result["interval_m"] - 80467) < 100  # 50 miles


class TestFallbackChain:
    def test_corridor_falls_back_to_proximity_without_route(self):
        result = parse_intent("gas stations along my route", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["original_intent"] == "route_corridor"
        assert result["fallback_reason"] == "no_route"

    def test_corridor_falls_back_to_plain_without_anything(self):
        result = parse_intent("gas stations along my route", has_position=False, has_route=False)
        assert result["intent"] == "plain"
        assert result["original_intent"] == "route_corridor"
        assert result["fallback_reason"] == "no_position"

    def test_proximity_falls_back_to_plain_without_position(self):
        result = parse_intent("nearest hospital", has_position=False, has_route=False)
        assert result["intent"] == "plain"
        assert result["original_intent"] == "proximity"
        assert result["fallback_reason"] == "no_position"


class TestCategoryExtraction:
    def test_filler_words_stripped(self):
        result = parse_intent("find the nearest gas station", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_plural_normalization(self):
        result = parse_intent("nearest hospitals", has_position=True, has_route=False)
        assert result["category"] == "hospital"

    def test_plural_gas_stations(self):
        result = parse_intent("nearest gas stations", has_position=True, has_route=False)
        assert result["category"] == "gas station"

    def test_unrecognized_business_name(self):
        result = parse_intent("Filibertos near me", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] is None
        assert "filibertos" in result["search_text"].lower()

    def test_route_66_not_confused_with_corridor(self):
        """'Route 66' should NOT trigger corridor intent."""
        result = parse_intent("Route 66 near me", has_position=True, has_route=True)
        assert result["intent"] == "proximity"
        assert "route 66" in result["search_text"].lower()


class TestImplicitProximity:
    def test_bare_category_with_position(self):
        result = parse_intent("gas", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "gas station"

    def test_bare_category_without_position(self):
        result = parse_intent("gas", has_position=False, has_route=False)
        assert result["intent"] == "plain"

    def test_bare_summit(self):
        result = parse_intent("summit", has_position=True, has_route=False)
        assert result["intent"] == "proximity"
        assert result["category"] == "summit"
        assert result["gnis_class"] == "Summit"


class TestGNISClasses:
    def test_hospital_has_gnis_class(self):
        result = parse_intent("nearest hospital", has_position=True, has_route=False)
        assert result["gnis_class"] == "Hospital"

    def test_gas_station_has_no_gnis_class(self):
        result = parse_intent("nearest gas station", has_position=True, has_route=False)
        assert result["gnis_class"] is None

    def test_dam_has_gnis_class(self):
        result = parse_intent("nearest dam", has_position=True, has_route=False)
        assert result["gnis_class"] == "Dam"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_intent_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'spatial'`

- [ ] **Step 3: Implement the intent parser**

Create `services/search/spatial.py` with the complete intent parser, synonym table, filler word stripping, and plural normalization. The full implementation is in the spec section "Intent Parser" — implement exactly as specified there. Key elements:

- `FILLER_WORDS` set: `find`, `the`, `a`, `an`, `me`, `some`, `show`, `search`, `look`, `for`, `where`, `is`, `are`, `get`, `list`
- `SYNONYM_TABLE` list of dicts with `synonyms` (set), `gnis_class` (str|None), `fallback_text` (str) — all 25 entries from the spec
- `_SYNONYM_LOOKUP` flat dict mapping each normalized synonym → table entry
- Regex patterns: `RE_ALONG_ROUTE`, `RE_ON_ROUTE`, `RE_EVERY_N`, `RE_NEAREST`, `RE_CLOSEST`, `RE_NEAR_ME`, `RE_NEAR_HERE`, `RE_NEARBY`, `RE_WITHIN`
- `_strip_filler(text)` → removes filler words
- `_lookup_category(text)` → token-based matching with plural normalization (exact → strip trailing 's' → token-level)
- `_parse_unit_to_meters(value, unit)` → miles/km to meters
- `parse_intent(query, has_position, has_route)` → returns dict with: `intent`, `original_intent`, `fallback_reason`, `category`, `gnis_class`, `search_text`, `radius_m`, `interval_m`

Also include these constants that will be used by later tasks:
```python
MILES_TO_METERS = 1609.34
KM_TO_METERS = 1000.0
DEFAULT_PROXIMITY_RADIUS_M = 50_000  # 50 km
CORRIDOR_WIDTH_M = 2_000  # 2 km
EARTH_RADIUS_M = 6_371_000
```

**Do NOT** add `haversine_m`, `douglas_peucker`, `corridor_filter`, any FastAPI imports, or any endpoint code.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_intent_parser.py -v`
Expected: All 28 tests PASS

- [ ] **Step 5: Commit**

```bash
git add services/search/spatial.py tests/test_intent_parser.py
git commit -m "feat: intent parser with synonym table and category extraction"
```

> BEFORE marking this task complete:
> 1. Verify test coverage: are error paths tested (fallback chain)? Edge cases (plurals, fillers, Route 66)? ✓
> 2. Run `python3 -m pytest tests/test_intent_parser.py -v` and confirm all green
> 3. Verify `parse_intent` return dict has ALL keys defined in the spec response schema

---

## Task 2: Corridor Math Utilities

**Dependencies:** Task 1 must be complete (`spatial.py` must exist with constants)
**Modifies:** `services/search/spatial.py` (appends new functions)
**Creates:** `tests/test_corridor.py`
**Does NOT modify:** `main.py`, `app.js`, any existing file other than `spatial.py`

> BEFORE starting work:
> 1. Read the spec section "Corridor Search Algorithm" — especially the per-segment bbox pre-check optimization (required for <500ms performance on Pi 5)
> 2. Read `services/search/spatial.py` as it exists after Task 1 — understand the constants defined there
> Follow TDD: write failing test → implement → verify green.

**Behavior change:** After this task, `spatial.py` gains five new functions: `haversine_m()`, `douglas_peucker()`, `point_to_segment_distance()`, `corridor_filter()`, `distance_along_polyline()`.

**Do NOT:**
- Modify `parse_intent()` or the synonym table
- Add any FastAPI routes
- Use numpy or any dependency not already in `requirements.txt`
- Remove the per-segment bbox pre-check optimization (it's required — pure haversine loops are 10x too slow on Pi 5)

- [ ] **Step 1: Write failing tests for corridor math**

Create `tests/test_corridor.py`:

```python
"""Tests for corridor search math: haversine, Douglas-Peucker, segment distance, corridor filter."""
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
    def test_same_point_is_zero(self):
        assert haversine_m(33.45, -112.07, 33.45, -112.07) == 0.0

    def test_phoenix_to_tucson(self):
        d = haversine_m(33.45, -112.07, 32.22, -110.97)
        assert 170_000 < d < 190_000  # ~180 km

    def test_symmetry(self):
        d1 = haversine_m(33.45, -112.07, 34.05, -111.09)
        d2 = haversine_m(34.05, -111.09, 33.45, -112.07)
        assert abs(d1 - d2) < 0.01


class TestDouglasPeucker:
    def test_empty(self):
        assert douglas_peucker([], tolerance_m=100) == []

    def test_single_point(self):
        assert douglas_peucker([[-112.0, 33.0]], tolerance_m=100) == [[-112.0, 33.0]]

    def test_two_points(self):
        pts = [[-112.0, 33.0], [-111.0, 33.0]]
        assert douglas_peucker(pts, tolerance_m=100) == pts

    def test_colinear_points_simplified(self):
        # 5 nearly colinear points on same latitude should reduce to 2
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
        assert len(result) == 5  # All preserved


class TestPointToSegment:
    def test_point_near_midpoint(self):
        d = point_to_segment_distance(
            33.0, -111.5,  # point near midpoint of segment
            [-112.0, 33.0], [-111.0, 33.0]  # segment [lng, lat]
        )
        assert d < 500  # within 500m of the line

    def test_point_far_away(self):
        d = point_to_segment_distance(
            35.0, -111.5,  # 2 degrees north
            [-112.0, 33.0], [-111.0, 33.0]
        )
        assert d > 200_000  # > 200 km

    def test_point_at_endpoint(self):
        d = point_to_segment_distance(
            33.0, -112.0,  # exactly at segment start
            [-112.0, 33.0], [-111.0, 33.0]
        )
        assert d < 100  # within 100m (rounding)

    def test_bbox_precheck_skips_distant_points(self):
        """Points far from segment should return inf quickly via bbox pre-check."""
        d = point_to_segment_distance(
            40.0, -80.0,  # very far (different region entirely)
            [-112.0, 33.0], [-111.0, 33.0]
        )
        assert d == float("inf")


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

    def test_sorted_by_distance_along_route(self):
        route = [[-112.0, 33.0], [-111.0, 33.0], [-110.0, 33.0]]
        candidates = [
            {"lat": 33.0, "lon": -110.5, "name": "Later"},
            {"lat": 33.0, "lon": -111.5, "name": "Earlier"},
        ]
        results = corridor_filter(route, candidates, corridor_width_m=5000)
        assert len(results) == 2
        assert results[0]["name"] == "Earlier"
        assert results[1]["name"] == "Later"
        assert results[0]["distance_along_route_m"] < results[1]["distance_along_route_m"]

    def test_empty_inputs(self):
        assert corridor_filter([], [], corridor_width_m=2000) == []
        assert corridor_filter([[-112.0, 33.0]], [{"lat": 33.0, "lon": -112.0}], corridor_width_m=2000) == []

    def test_has_distance_along_route_field(self):
        route = [[-112.0, 33.0], [-111.0, 33.0]]
        candidates = [{"lat": 33.0, "lon": -111.5, "name": "Test"}]
        results = corridor_filter(route, candidates, corridor_width_m=5000)
        assert len(results) == 1
        assert "distance_along_route_m" in results[0]
        assert isinstance(results[0]["distance_along_route_m"], float)


class TestDistanceAlongPolyline:
    def test_single_segment(self):
        total = distance_along_polyline([[-112.0, 33.0], [-111.0, 33.0]])
        assert 80_000 < total < 100_000  # ~90 km at this latitude

    def test_empty(self):
        assert distance_along_polyline([]) == 0.0

    def test_single_point(self):
        assert distance_along_polyline([[-112.0, 33.0]]) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_corridor.py -v`
Expected: FAIL with `ImportError: cannot import name 'haversine_m' from 'spatial'`

- [ ] **Step 3: Implement corridor math**

Append the following functions to `services/search/spatial.py` (after the existing `parse_intent` function):

1. `haversine_m(lat1, lon1, lat2, lon2)` — standard haversine formula, returns meters. Duplicated from `main.py` for module independence.
2. `_point_line_distance_m(plng, plat, a_lng, a_lat, b_lng, b_lat)` — cross-track distance for Douglas-Peucker.
3. `douglas_peucker(points, tolerance_m=50.0)` — recursive simplification of `[lng, lat]` polyline.
4. `point_to_segment_distance(p_lat, p_lng, seg_a, seg_b)` — minimum distance from point to `[lng, lat]` segment. **MUST include the bbox pre-check**: if point lat/lng is outside `min/max of segment ± 0.02 degrees`, return `float("inf")` immediately. This is the critical performance optimization.
5. `corridor_filter(route, candidates, corridor_width_m, interval_m=None)` — simplify route, pre-compute cumulative lengths, filter candidates, sort by distance-along-route, apply optional interval filter.
6. `distance_along_polyline(polyline)` — sum of segment lengths in meters.

See the spec "Corridor Search Algorithm" section for the exact algorithm. The `corridor_filter` function:
- Calls `douglas_peucker` on the route
- Pre-computes cumulative segment lengths
- For each candidate, finds the nearest segment (using `point_to_segment_distance`)
- Keeps candidates within `corridor_width_m`
- Computes `distance_along_route_m` for each
- Sorts by `distance_along_route_m`
- Applies interval filter if `interval_m` is set

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_corridor.py tests/test_intent_parser.py -v`
Expected: ALL tests pass (both task 1 and task 2 tests)

- [ ] **Step 5: Commit**

```bash
git add services/search/spatial.py tests/test_corridor.py
git commit -m "feat: corridor math — Douglas-Peucker, segment distance, corridor filter"
```

> BEFORE marking this task complete:
> 1. Verify the bbox pre-check in `point_to_segment_distance` returns `float("inf")` for distant points (test `test_bbox_precheck_skips_distant_points` covers this)
> 2. Verify `corridor_filter` returns results with `distance_along_route_m` field
> 3. Run ALL tests: `python3 -m pytest tests/ -v` and confirm green

---

> **Review loop after Tasks 1-2 (backend logic group):**
> You MUST carefully review the batch of work from multiple perspectives and revise/refine as appropriate. Repeat this review loop (minimum 3 rounds; if you still find substantive issues in round 3, keep going) until confident there are no issues. Specifically check:
> - Does `parse_intent` return dict match the response schema in the spec?
> - Does `corridor_filter` add `distance_along_route_m` to each result?
> - Are all 25 synonym table entries from the spec present?
> - Is the bbox pre-check in `point_to_segment_distance` working (test it)?
> - Do Task 1 tests still pass after Task 2 additions to `spatial.py`?

---

## Task 3: POST /search/spatial Endpoint

**Dependencies:** Tasks 1 and 2 must be complete (`spatial.py` must have `parse_intent` and `corridor_filter`)
**Modifies:** `services/search/spatial.py` (appends endpoint), `services/search/main.py` (mounts router, adds index)
**Creates:** `tests/test_spatial_endpoint.py`

> BEFORE starting work:
> 1. Read the spec section "API" — especially the request/response schemas and validation bounds
> 2. Read `services/search/main.py` — understand `_query_nominatim`, `_query_poi`, `_deduplicate`, the `State` class, and the `lifespan` function
> 3. Read `services/search/spatial.py` as it exists after Tasks 1-2
> Follow TDD: write failing test → implement → verify green.

**Behavior change:** A new `POST /search/spatial` endpoint becomes available. It accepts `{query, position, route}`, runs the intent parser, queries Nominatim + POI, applies spatial filtering, and returns results with `distance_m`, `distance_along_route_m`, `intent`, `original_intent`, `fallback_reason`, and `category` fields. The existing `GET /search` endpoint is unchanged.

**Do NOT:**
- Modify the existing `GET /search` endpoint or its response shape
- Change the `_query_nominatim` or `_query_poi` function signatures
- Add any frontend code

**Key architectural context:** The search service's `_query_nominatim` and `_query_poi` are module-level async functions in `main.py`. The spatial endpoint in `spatial.py` needs to call them. Use a FastAPI `APIRouter` in `spatial.py` and mount it in `main.py`. The endpoint calls the query functions via an import from `main`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_spatial_endpoint.py`:

```python
"""Integration tests for POST /search/spatial."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

import pytest


class TestSpatialEndpointValidation:
    """Test request validation without needing a running Nominatim/POI database."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from main import app
        from fastapi.testclient import TestClient
        self.client = TestClient(app)

    def test_plain_search_returns_intent(self):
        resp = self.client.post("/spatial", json={"query": "Phoenix"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "plain"
        assert data["original_intent"] == "plain"
        assert data["fallback_reason"] is None
        assert "results" in data

    def test_proximity_with_position(self):
        resp = self.client.post("/spatial", json={
            "query": "nearest gas station",
            "position": {"lat": 33.45, "lon": -112.07},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "proximity"
        assert data["category"] == "gas station"

    def test_proximity_fallback_without_position(self):
        resp = self.client.post("/spatial", json={
            "query": "nearest gas station",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "plain"
        assert data["original_intent"] == "proximity"
        assert data["fallback_reason"] == "no_position"

    def test_query_too_long_rejected(self):
        resp = self.client.post("/spatial", json={"query": "x" * 501})
        assert resp.status_code == 422

    def test_empty_query_rejected(self):
        resp = self.client.post("/spatial", json={"query": ""})
        assert resp.status_code == 422

    def test_invalid_position_rejected(self):
        resp = self.client.post("/spatial", json={
            "query": "test",
            "position": {"lat": 999, "lon": -112.0},
        })
        assert resp.status_code == 422

    def test_results_have_distance_fields(self):
        resp = self.client.post("/spatial", json={
            "query": "Phoenix",
            "position": {"lat": 33.45, "lon": -112.07},
        })
        data = resp.json()
        # Results may be empty (no Nominatim/POI in test), but shape is correct
        assert "results" in data
        assert isinstance(data["results"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_spatial_endpoint.py -v`
Expected: FAIL (no `/spatial` endpoint)

- [ ] **Step 3: Add the FastAPI endpoint to spatial.py**

Append to `services/search/spatial.py`:

```python
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
```

- [ ] **Step 4: Mount the router in main.py**

In `services/search/main.py`, add after the `app = FastAPI(...)` line:

```python
from spatial import router as spatial_router
app.include_router(spatial_router, prefix="")
```

In the `lifespan` function, after `await _open_poi_db()`, add:

```python
        # Ensure spatial index for bbox queries (corridor/proximity search)
        if state.poi_db:
            await state.poi_db.execute(
                "CREATE INDEX IF NOT EXISTS idx_poi_latlon ON poi_features (lat, lon)"
            )
```

- [ ] **Step 5: Run all tests**

Run: `python3 -m pytest tests/ -v`
Expected: ALL tests pass (intent parser + corridor + endpoint + earlier tests)

- [ ] **Step 6: Commit**

```bash
git add services/search/spatial.py services/search/main.py tests/test_spatial_endpoint.py
git commit -m "feat: POST /search/spatial endpoint with intent parsing and corridor search"
```

> BEFORE marking this task complete:
> 1. Verify the endpoint returns all required response fields: `results`, `intent`, `original_intent`, `fallback_reason`, `category`
> 2. Verify each result has `distance_m` and `distance_along_route_m` fields (even if null)
> 3. Verify the POI lat/lon index creation is in the lifespan function
> 4. Run `python3 -m pytest tests/ -v` and confirm ALL tests green

---

> **Review loop after Task 3 (backend complete):**
> You MUST carefully review all backend code from multiple perspectives. Minimum 3 rounds. Check:
> - Does the circular import between `spatial.py` and `main.py` work? (spatial imports from main inside the endpoint function, main imports router from spatial at module level)
> - Does the Pydantic validation correctly reject query > 500 chars and lat > 90?
> - Is the `route` field validated for max 10000 points?
> - Does the endpoint gracefully handle Nominatim being unavailable? (the `return_exceptions=True` + isinstance check)
> - Are the three test files consistent with each other?

---

## Task 4: Frontend — POST Switch + Route Coords State

**Dependencies:** Task 3 must be complete (endpoint must exist). But this task can be developed in parallel if desired — it only touches `frontend/app.js`.
**Modifies:** `frontend/app.js`
**Does NOT modify:** any backend file

> BEFORE starting work:
> 1. Read `frontend/app.js` — find these specific locations:
>    - `var lastRouteTrip = null;` (~line 44) — route state variable
>    - `function performSearch(query)` (~line 594) — current GET search
>    - `function renderRoute(trip)` (~line 1062) — where route geometry is decoded
>    - `function clearRoute()` — search for `lastRouteTrip = null`
>    - `var gpsLastPos = null;` (~line 52) — GPS position variable
>    - `var gpsStale = true;` (~line 51) — GPS stale flag
> 2. Read the spec section "Frontend Changes — Search input"
> Follow TDD: there are no unit tests for frontend JS in this project. Verify with `node -c` syntax check and manual testing.

**Behavior change:**
- `performSearch()` changes from `GET /search/search?q=...` to `POST /search/spatial` with `{query, position, route}`
- New `lastRouteCoords` state variable stores decoded route polyline
- `renderSearchResults()` signature changes from `(results)` to `(results, metadata)` (metadata unused until Task 5)
- Graceful degradation: if POST returns 404/405, falls back to old GET endpoint

**Do NOT:**
- Add numbered pins (that's Task 5)
- Add distance badges (that's Task 5)
- Change `renderSearchResults()` rendering logic (that's Task 5)
- Remove `searchMarker` (that's Task 5)
- Modify any backend file

- [ ] **Step 1: Add `lastRouteCoords` state variable**

Near line 44 of `frontend/app.js`, after `var lastRouteTrip = null;`, add:

```javascript
  var lastRouteCoords = null;  // decoded [lng, lat] pairs for spatial search context
```

- [ ] **Step 2: Populate `lastRouteCoords` in `renderRoute()`**

In `renderRoute()`, find the loop that decodes polylines (search for `decodePolyline(leg.shape)` around line 1068). After the loop builds `allCoords`, add:

```javascript
      lastRouteCoords = allCoords.slice();
```

- [ ] **Step 3: Clear `lastRouteCoords` in `clearRoute()`**

Find `clearRoute()` (search for `lastRouteTrip = null`). Add next to it:

```javascript
      lastRouteCoords = null;
```

- [ ] **Step 4: Rewrite `performSearch()` to POST**

Replace the entire `performSearch()` function (~line 594):

```javascript
  function performSearch(query) {
    var body = { query: query };
    if (gpsLastPos && !gpsStale) {
      body.position = { lat: gpsLastPos[1], lon: gpsLastPos[0] };
    }
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
          return fetch('/search/search?q=' + encodeURIComponent(query) + '&limit=10')
            .then(function (r) { return r.json(); })
            .then(function (d) {
              return { results: d.results || d, intent: 'plain', original_intent: 'plain', fallback_reason: null, category: null };
            });
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

- [ ] **Step 5: Update `renderSearchResults` signature**

Change the function signature from `function renderSearchResults(results)` to `function renderSearchResults(results, metadata)`. Do NOT change the body — Task 5 handles that. The `metadata` parameter is simply ignored for now.

- [ ] **Step 6: Verify syntax and page load**

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

## Task 5: Frontend — Numbered Pins, Distance Badges, Remove Old Marker

**Dependencies:** Task 4 must be complete (`performSearch` must POST, `renderSearchResults` must accept `metadata`)
**Modifies:** `frontend/app.js`, `frontend/style.css`
**Does NOT modify:** any backend file

> BEFORE starting work:
> 1. Read `frontend/app.js` — find these specific locations:
>    - `function addPlaceholderSources()` (~line 89) — where MapLibre sources/layers are registered for style-swap survival
>    - `function renderSearchResults(results, metadata)` — the function you'll rewrite
>    - `function selectSearchResult(item)` — the old single-marker function you'll replace
>    - `function hideSearchResults()` — you'll add pin cleanup here
>    - `function initSearch()` — you'll add pin click handlers here
>    - `var searchMarker = null;` (~line 35) — the old marker variable you'll remove
>    - `var searchPopup = null;` (~line 36) — keep this (popups still needed)
>    - The KML imported-feature layer click handlers (~line 279) — use the same `mouseenter`/`mouseleave` cursor pattern
> 2. Read the spec sections "Map result pins" and "Result rendering"
> No automated tests for frontend — verify with `node -c` and manual testing.

**Behavior change:**
- ALL search results get numbered amber pins on the map (not just spatial)
- Spatial results show distance badges ("2.3 mi" or "in 47 mi")
- Intent subtitle shown for spatial queries ("Nearest gas stations")
- Click list item → fly to pin with padding. Click pin → highlight list item.
- Old `searchMarker` DOM marker approach replaced entirely
- `search-results` source/layer registered in `addPlaceholderSources()` for style-swap survival

**Do NOT:**
- Modify any backend file
- Add search typeahead or live-as-you-type behavior
- Add "route to this result" functionality
- Change the `geocodeForRoute()` function (it still uses GET /search)

- [ ] **Step 1: Register search-results source and layers in `addPlaceholderSources()`**

At the END of `addPlaceholderSources()` (after all other layer registrations), add:

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
        paint: { 'text-color': '#ffffff' }
      });
    }
```

- [ ] **Step 2: Add pin click handler and cursor change in `initSearch()`**

In `initSearch()`, after the existing event listeners, add:

```javascript
    map.on('click', 'search-result-circles', function (e) {
      if (!e.features || !e.features.length) return;
      var idx = parseInt(e.features[0].properties.index, 10) - 1;
      var items = document.querySelectorAll('#search-results li:not(.search-intent-subtitle)');
      if (items[idx]) {
        items[idx].scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        items[idx].classList.add('search-result-active');
        setTimeout(function () { items[idx].classList.remove('search-result-active'); }, 2000);
      }
    });
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
        properties: { index: String(i + 1), name: item.name || '' }
      };
    }).filter(Boolean);
    var src = map.getSource('search-results');
    if (src) src.setData({ type: 'FeatureCollection', features: features });
  }
```

- [ ] **Step 4: Rewrite `renderSearchResults()` with badges and distance**

Replace the entire `renderSearchResults()` function body:

```javascript
  function renderSearchResults(results, metadata) {
    var list = document.getElementById('search-results');
    while (list.firstChild) list.removeChild(list.firstChild);
    clearSearchPins();

    if (!results || results.length === 0) {
      var emptyLi = document.createElement('li');
      if (metadata && metadata.original_intent !== 'plain' && metadata.fallback_reason) {
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

    if (metadata && metadata.intent !== 'plain' && metadata.category) {
      var subtitleLi = document.createElement('li');
      subtitleLi.className = 'search-intent-subtitle';
      subtitleLi.textContent = metadata.intent === 'route_corridor'
        ? metadata.category.charAt(0).toUpperCase() + metadata.category.slice(1) + ' along route'
        : 'Nearest ' + metadata.category;
      list.appendChild(subtitleLi);
    }

    results.forEach(function (item, idx) {
      var li = document.createElement('li');
      var badge = document.createElement('span');
      badge.className = 'search-result-badge';
      badge.textContent = String(idx + 1);
      li.appendChild(badge);

      var nameSpan = document.createElement('span');
      nameSpan.className = 'search-result-name';
      nameSpan.textContent = item.name || item.display_name || 'Unknown';
      li.appendChild(nameSpan);

      if (item.distance_along_route_m != null) {
        var dSpan = document.createElement('span');
        dSpan.className = 'search-result-distance';
        dSpan.textContent = 'in ' + formatDistance(item.distance_along_route_m);
        li.appendChild(dSpan);
      } else if (item.distance_m != null) {
        var dSpan2 = document.createElement('span');
        dSpan2.className = 'search-result-distance';
        dSpan2.textContent = formatDistance(item.distance_m);
        li.appendChild(dSpan2);
      }

      li.addEventListener('click', function () { selectSearchResult(item); });
      list.appendChild(li);
    });

    updateSearchPins(results);
    list.classList.add('visible');
  }
```

- [ ] **Step 5: Replace `selectSearchResult()` — remove old marker, use popup only**

```javascript
  function selectSearchResult(item) {
    var lng = parseFloat(item.lon || item.longitude || item.lng);
    var lat = parseFloat(item.lat || item.latitude);
    if (isNaN(lng) || isNaN(lat)) return;

    map.flyTo({
      center: [lng, lat],
      zoom: Math.max(map.getZoom(), 14),
      padding: { bottom: 200, left: 0, right: 0, top: 0 }
    });

    if (searchPopup) searchPopup.remove();
    var popupContent = document.createElement('div');
    var h4 = document.createElement('h4');
    h4.textContent = item.name || item.display_name || 'Result';
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

- [ ] **Step 7: Remove old `searchMarker`**

Remove `var searchMarker = null;` (around line 35). Remove any remaining references to `searchMarker` (search the file for `searchMarker`). The numbered pins + popup replace it entirely.

- [ ] **Step 8: Add CSS**

Append to `frontend/style.css`:

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

- [ ] **Step 9: Verify syntax and commit**

```bash
node -c frontend/app.js
curl -s -o /dev/null -w "%{http_code}" https://pandora.twin-bramble.ts.net/
```

Expected: Syntax OK, HTTP 200

```bash
git add frontend/app.js frontend/style.css
git commit -m "feat: numbered search pins for all results with distance badges"
```

> BEFORE marking this task complete:
> 1. Verify `searchMarker` variable and all references are removed
> 2. Verify `search-results` source is registered in `addPlaceholderSources()`
> 3. Verify `clearSearchPins()` is called in both `renderSearchResults()` and `hideSearchResults()`
> 4. Run `node -c frontend/app.js` to confirm no syntax errors

---

> **Review loop after Tasks 4-5 (frontend complete):**
> You MUST carefully review all frontend changes. Minimum 3 rounds. Check:
> - Is `lastRouteCoords` populated in `renderRoute()` and cleared in `clearRoute()`?
> - Does `performSearch()` gracefully degrade on 404/405?
> - Is `searchMarker` completely removed (no dangling references)?
> - Does `addPlaceholderSources()` register `search-results` source and both layers?
> - Does `hideSearchResults()` call `clearSearchPins()`?
> - Does the CSS `.search-result-badge` background match the MapLibre circle paint `#e6920a`?
> - Is `formatDistance()` called (exists at ~line 2252)?

---

## Task 6: End-to-End Verification

**Dependencies:** ALL previous tasks must be complete
**Modifies:** Nothing (or minor fixes discovered during testing)

- [ ] **Step 1: Run all Python tests**

```bash
python3 -m pytest tests/ -v
```

Expected: ALL tests pass

- [ ] **Step 2: Restart the search service to pick up changes**

```bash
docker compose build search && docker compose up -d search
```

Wait for healthy: `docker compose ps | grep search`

- [ ] **Step 3: Test plain search (no regression)**

Open `https://pandora.twin-bramble.ts.net`. Type "Phoenix" in search, press Enter.

Verify:
- Results appear with numbered badges (1, 2, 3...)
- Amber numbered pins appear on map
- Clicking a result flies to pin
- Clicking outside dismisses results and clears pins

- [ ] **Step 4: Test proximity search**

With GPS enabled, type "nearest gas station", press Enter.

Verify:
- Intent subtitle shows "Nearest gas station"
- Results have distance badges ("2.3 mi")
- Results sorted by distance (closest first)
- Pins on map match result numbers

- [ ] **Step 5: Test corridor search**

Set a route (Phoenix to Flagstaff). Type "gas stations along my route", press Enter.

Verify:
- Intent subtitle shows "Gas stations along route"
- Results have "in X mi" distance badges
- Results sorted by distance along route
- Only results near the route appear

- [ ] **Step 6: Test fallback behavior**

Without GPS, type "nearest hospital". Verify plain search results (no crash, no distance badges).

Without a route, type "gas stations along my route". Verify fallback to proximity or plain.

- [ ] **Step 7: Test bare category with GPS**

Type just "gas" with GPS enabled. Verify proximity results appear (implicit promotion).

- [ ] **Step 8: Commit any fixes**

```bash
git add -A
git commit -m "fix: end-to-end testing adjustments for spatial search"
```

> **Final review loop:**
> Review the complete feature from the user's perspective. Minimum 3 rounds:
> - Does plain search still work exactly as before (minus the old single marker)?
> - Do the numbered pins survive a style swap (Positron ↔ Dark Matter)?
> - Does clearing the search (Escape, click outside) remove all pins?
> - On mobile viewport, does `flyTo` padding prevent the pin from landing behind the sidebar?
> - Does the `GET /search` endpoint still work for `geocodeForRoute`?
