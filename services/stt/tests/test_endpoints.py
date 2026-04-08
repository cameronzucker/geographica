"""Tests for FastAPI STT endpoints.

Uses a mock backend to avoid loading the real Whisper model.
"""

import io
import struct
import sys

import numpy as np
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from backends import TranscribeResult


@pytest.fixture
def mock_backend():
    """Mock backend module with load_model and transcribe."""
    backend = MagicMock()
    backend.load_model = MagicMock()
    backend.transcribe = MagicMock(
        return_value=TranscribeResult(text="gas stations near me", duration_ms=2847)
    )
    return backend


@pytest.fixture
def client(mock_backend, monkeypatch):
    """Create a TestClient with mocked backend.

    Bypasses the lifespan model loading by directly setting the
    module-level _backend reference after import.
    """
    monkeypatch.setenv("STT_BACKEND", "cpu")
    monkeypatch.setenv("MODEL_PATH", "/opt/models/faster-whisper-base.en")

    import importlib

    # Remove cached main module to force clean re-import
    if "main" in sys.modules:
        del sys.modules["main"]

    import main

    # Replace the lifespan with one that doesn't load the real model
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def mock_lifespan(app):
        main._backend = mock_backend
        main._backend_name = "cpu"
        yield

    main.app.router.lifespan_context = mock_lifespan

    with TestClient(main.app) as c:
        yield c


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_ok(self, client):
        """Health endpoint should return status ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "backend" in data

    def test_health_includes_backend_name(self, client):
        """Health should report the active backend."""
        resp = client.get("/health")
        data = resp.json()
        assert data["backend"] == "cpu"

    def test_health_includes_model_name(self, client):
        """Health should report the model name."""
        resp = client.get("/health")
        data = resp.json()
        assert data["model"] == "base.en"


class TestTranscribeEndpoint:
    """Tests for POST /transcribe."""

    def test_transcribe_valid_wav(self, client, wav_bytes_factory):
        """Valid WAV should return transcribed text."""
        wav = wav_bytes_factory(duration_s=2.0)
        resp = client.post(
            "/transcribe",
            files={"audio": ("test.wav", io.BytesIO(wav), "audio/wav")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "text" in data
        assert "duration_ms" in data
        assert "backend" in data

    def test_transcribe_rejects_non_wav(self, client):
        """Non-WAV data should return 422."""
        resp = client.post(
            "/transcribe",
            files={"audio": ("test.wav", io.BytesIO(b"not a wav file"), "audio/wav")},
        )
        assert resp.status_code == 422

    def test_transcribe_rejects_wrong_sample_rate(self, client, wav_bytes_factory):
        """WAV with wrong sample rate should return 422."""
        wav = wav_bytes_factory(sample_rate=44100)
        resp = client.post(
            "/transcribe",
            files={"audio": ("test.wav", io.BytesIO(wav), "audio/wav")},
        )
        assert resp.status_code == 422

    def test_transcribe_rejects_stereo(self, client, wav_bytes_factory):
        """Stereo WAV should return 422."""
        wav = wav_bytes_factory(num_channels=2)
        resp = client.post(
            "/transcribe",
            files={"audio": ("test.wav", io.BytesIO(wav), "audio/wav")},
        )
        assert resp.status_code == 422

    def test_transcribe_rejects_oversized(self, client):
        """WAV > 1MB should return 413."""
        # Create a WAV that's just over 1MB
        big_wav = b"RIFF" + b"\x00" * (1024 * 1024 + 100)
        resp = client.post(
            "/transcribe",
            files={"audio": ("test.wav", io.BytesIO(big_wav), "audio/wav")},
        )
        assert resp.status_code == 413

    def test_transcribe_too_short_returns_reason(self, client, wav_bytes_factory):
        """WAV < 0.5s should return 200 with reason=too_short."""
        wav = wav_bytes_factory(duration_s=0.3)
        resp = client.post(
            "/transcribe",
            files={"audio": ("test.wav", io.BytesIO(wav), "audio/wav")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == ""
        assert data["reason"] == "too_short"

    def test_transcribe_truncates_long_audio(self, client, wav_bytes_factory, mock_backend):
        """WAV > 15s should be truncated and flagged."""
        wav = wav_bytes_factory(duration_s=20.0)
        resp = client.post(
            "/transcribe",
            files={"audio": ("test.wav", io.BytesIO(wav), "audio/wav")},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("truncated") is True


class TestBackendDispatch:
    """Tests for backend selection via STT_BACKEND env var."""

    def test_default_backend_is_cpu(self, monkeypatch):
        """Without STT_BACKEND env var, default to cpu."""
        monkeypatch.delenv("STT_BACKEND", raising=False)
        import importlib

        if "main" in sys.modules:
            del sys.modules["main"]
        import main

        assert main.STT_BACKEND == "cpu"
