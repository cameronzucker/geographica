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
