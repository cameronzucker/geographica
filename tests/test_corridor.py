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
        # Points on the same latitude are not perfectly colinear on a sphere
        # (great circle curves), so use a generous tolerance
        pts = [[-112.0, 33.0], [-111.5, 33.0], [-111.0, 33.0],
               [-110.5, 33.0], [-110.0, 33.0]]
        result = douglas_peucker(pts, tolerance_m=5000)
        assert len(result) == 2
        assert result[0] == pts[0]
        assert result[-1] == pts[-1]

    def test_zigzag_preserved(self):
        pts = [[-112.0, 33.0], [-111.5, 34.0], [-111.0, 33.0],
               [-110.5, 34.0], [-110.0, 33.0]]
        result = douglas_peucker(pts, tolerance_m=100)
        assert len(result) == 5


class TestPointToSegment:
    def test_point_near_midpoint(self):
        d = point_to_segment_distance(
            33.0, -111.5,
            [-112.0, 33.0], [-111.0, 33.0]
        )
        assert d < 500

    def test_point_far_away(self):
        d = point_to_segment_distance(
            35.0, -111.5,
            [-112.0, 33.0], [-111.0, 33.0]
        )
        assert d > 200_000

    def test_point_at_endpoint(self):
        d = point_to_segment_distance(
            33.0, -112.0,
            [-112.0, 33.0], [-111.0, 33.0]
        )
        assert d < 100

    def test_bbox_precheck_skips_distant_points(self):
        d = point_to_segment_distance(
            40.0, -80.0,
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
        assert 80_000 < total < 100_000

    def test_empty(self):
        assert distance_along_polyline([]) == 0.0

    def test_single_point(self):
        assert distance_along_polyline([[-112.0, 33.0]]) == 0.0
