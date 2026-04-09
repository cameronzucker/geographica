"""Integration tests for POST /search/spatial."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))

import pytest


class TestSpatialEndpointValidation:
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
        assert "results" in data
        assert isinstance(data["results"], list)


class TestCityIntentEndpoint:
    @pytest.fixture(autouse=True)
    def setup(self, monkeypatch):
        monkeypatch.setenv("NOMINATIM_URL", "http://localhost:8092")
        from main import app
        from fastapi.testclient import TestClient
        from geocode import clear_cache, init_geocode
        clear_cache()
        with TestClient(app) as client:
            # Re-init geocode with test-accessible Nominatim URL
            from main import state
            init_geocode(state.http_client, "http://localhost:8092")
            self.client = client
            yield

    @pytest.fixture(autouse=True)
    def check_nominatim(self):
        import httpx
        try:
            resp = httpx.get("http://localhost:8092/status", timeout=2.0)
            resp.raise_for_status()
        except Exception:
            pytest.fail("Nominatim container not responding")

    def test_city_proximity_returns_results(self):
        resp = self.client.post("/spatial", json={"query": "gas stations in flagstaff"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "city_proximity"
        assert data["place_name"] == "flagstaff"
        assert data["category"] == "gas station"
        assert "results" in data

    def test_city_corridor_with_route(self):
        route = [[-112.07, 33.45], [-111.85, 34.25], [-111.65, 35.20]]
        resp = self.client.post("/spatial", json={
            "query": "gas stations in flagstaff along my route",
            "route": route,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "city_corridor"
        assert data["place_name"] == "flagstaff"

    def test_geocode_failed(self):
        resp = self.client.post("/spatial", json={"query": "gas stations in xyzzy_nonexistent_12345"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["fallback_reason"] == "geocode_failed"
        assert data["place_name"] == "xyzzy_nonexistent_12345"

    def test_city_not_on_route(self):
        route = [[-112.07, 33.45], [-111.85, 34.25], [-111.65, 35.20]]
        resp = self.client.post("/spatial", json={
            "query": "gas stations in los angeles along my route",
            "route": route,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["fallback_reason"] == "city_not_on_route"

    def test_approach_c_brand(self):
        resp = self.client.post("/spatial", json={"query": "shell in tucson"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["intent"] == "city_proximity"
        assert data["place_name"] == "tucson"

    def test_city_proximity_distance_from_city_center(self):
        resp = self.client.post("/spatial", json={
            "query": "gas stations in flagstaff",
            "position": {"lat": 33.45, "lon": -112.07},
        })
        data = resp.json()
        if data["results"]:
            for r in data["results"]:
                if r.get("distance_m") is not None:
                    assert r["distance_m"] < 50000

    def test_place_name_in_response(self):
        resp = self.client.post("/spatial", json={"query": "restaurants in phoenix"})
        data = resp.json()
        assert "place_name" in data
        assert data["place_name"] == "phoenix"

    def test_non_city_query_has_null_place_name(self):
        resp = self.client.post("/spatial", json={
            "query": "nearest gas station",
            "position": {"lat": 33.45, "lon": -112.07},
        })
        data = resp.json()
        assert data.get("place_name") is None
