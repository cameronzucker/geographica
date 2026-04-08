"""Integration test: transcribe WAV -> spatial search pipeline.

Tests the two-step frontend flow without a browser:
1. POST /stt/transcribe with WAV -> receive {text}
2. POST /search/spatial with text + GPS coords -> receive results

Requires:
- STT service running at localhost:8098 (or STT_URL env var)
- Search service running at localhost:8096 (or SEARCH_URL env var)

Skip if services are not running.
"""

import io
import os
from pathlib import Path

import pytest
import requests

STT_URL = os.environ.get("STT_URL", "http://localhost:8098")
SEARCH_URL = os.environ.get("SEARCH_URL", "http://localhost:8096")
FIXTURES = Path(__file__).parent / "fixtures"


def _service_available(url: str) -> bool:
    """Check if a service is reachable."""
    try:
        resp = requests.get(f"{url}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


stt_available = _service_available(STT_URL)
search_available = _service_available(SEARCH_URL)

pytestmark = pytest.mark.skipif(
    not (stt_available and search_available),
    reason="STT and/or Search service not running",
)


class TestTranscribePipeline:
    """End-to-end transcribe -> spatial search tests."""

    def test_health_endpoints(self):
        """Both services should be healthy."""
        stt_resp = requests.get(f"{STT_URL}/health")
        assert stt_resp.status_code == 200
        assert stt_resp.json()["status"] == "ok"

        search_resp = requests.get(f"{SEARCH_URL}/health")
        assert search_resp.status_code == 200
        assert search_resp.json()["status"] == "ok"

    def test_transcribe_fixture_wav(self):
        """POST fixture WAV to /transcribe should return a result."""
        wav_path = FIXTURES / "test_audio.wav"
        assert wav_path.exists(), f"Fixture not found: {wav_path}"

        with open(wav_path, "rb") as f:
            resp = requests.post(
                f"{STT_URL}/transcribe",
                files={"audio": ("test.wav", f, "audio/wav")},
                timeout=30,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "backend" in data
        assert "duration_ms" in data
        assert data["backend"] in ("cpu", "npu")

    def test_transcribe_then_spatial_search(self):
        """Full pipeline: transcribe audio, then search with result text."""
        wav_path = FIXTURES / "test_audio.wav"

        # Step 1: Transcribe
        with open(wav_path, "rb") as f:
            stt_resp = requests.post(
                f"{STT_URL}/transcribe",
                files={"audio": ("test.wav", f, "audio/wav")},
                timeout=30,
            )
        assert stt_resp.status_code == 200
        stt_data = stt_resp.json()

        # The fixture is a sine wave, so text may be empty.
        # Use a fallback query for the spatial search test.
        query_text = stt_data.get("text") or "gas stations"

        # Step 2: Spatial search with the transcribed text
        search_resp = requests.post(
            f"{SEARCH_URL}/spatial",
            json={
                "query": query_text,
                "lat": 34.0,
                "lon": -111.9,
            },
            timeout=10,
        )
        assert search_resp.status_code == 200
        search_data = search_resp.json()
        assert "results" in search_data or "intent" in search_data

    def test_reject_invalid_wav(self):
        """Invalid audio should return 422."""
        resp = requests.post(
            f"{STT_URL}/transcribe",
            files={"audio": ("bad.wav", io.BytesIO(b"not a wav"), "audio/wav")},
            timeout=10,
        )
        assert resp.status_code == 422
