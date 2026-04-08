"""Tests for the CPU (faster-whisper) backend.

These tests require the faster-whisper package to be installed.
They use a small synthetic audio fixture, not real speech.
"""

import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backends import TranscribeResult


FIXTURES = Path(__file__).parent / "fixtures"


class TestCpuBackendLoadModel:
    """Tests for cpu.load_model()."""

    def test_load_model_creates_whisper_model(self):
        """load_model should instantiate WhisperModel with correct params."""
        with patch("backends.cpu.WhisperModel") as mock_cls:
            from backends.cpu import load_model

            load_model("/opt/models/faster-whisper-base.en")
            mock_cls.assert_called_once_with(
                "/opt/models/faster-whisper-base.en",
                device="cpu",
                compute_type="int8",
            )

    def test_load_model_stores_model_reference(self):
        """After load_model, the module-level _model should be set."""
        with patch("backends.cpu.WhisperModel") as mock_cls:
            mock_cls.return_value = MagicMock()
            from backends import cpu

            cpu.load_model("/opt/models/faster-whisper-base.en")
            assert cpu._model is not None


class TestCpuBackendTranscribe:
    """Tests for cpu.transcribe()."""

    def test_transcribe_returns_transcribe_result(self):
        """transcribe() must return a TranscribeResult instance."""
        mock_segment = MagicMock()
        mock_segment.text = " hello world"
        mock_segment.no_speech_prob = 0.1
        mock_segment.avg_logprob = -0.3

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], MagicMock())

        with patch("backends.cpu._model", mock_model):
            from backends.cpu import transcribe

            audio = np.zeros(16000, dtype=np.float32)
            result = transcribe(audio, 16000)
            assert isinstance(result, TranscribeResult)
            assert result.text == "hello world"
            assert result.duration_ms >= 0

    def test_transcribe_filters_no_speech(self):
        """Segments with no_speech_prob > 0.8 should produce empty text."""
        mock_segment = MagicMock()
        mock_segment.text = " [silence]"
        mock_segment.no_speech_prob = 0.9  # above threshold
        mock_segment.avg_logprob = -0.3

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], MagicMock())

        with patch("backends.cpu._model", mock_model):
            from backends.cpu import transcribe

            audio = np.zeros(16000, dtype=np.float32)
            result = transcribe(audio, 16000)
            assert result.text == ""

    def test_transcribe_filters_low_logprob(self):
        """Segments with avg_logprob < -0.8 should produce empty text."""
        mock_segment = MagicMock()
        mock_segment.text = " garbled"
        mock_segment.no_speech_prob = 0.3
        mock_segment.avg_logprob = -1.2  # below threshold

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([mock_segment], MagicMock())

        with patch("backends.cpu._model", mock_model):
            from backends.cpu import transcribe

            audio = np.zeros(16000, dtype=np.float32)
            result = transcribe(audio, 16000)
            assert result.text == ""

    def test_transcribe_concatenates_segments(self):
        """Multiple valid segments should be concatenated."""
        seg1 = MagicMock()
        seg1.text = " hello"
        seg1.no_speech_prob = 0.1
        seg1.avg_logprob = -0.3

        seg2 = MagicMock()
        seg2.text = " world"
        seg2.no_speech_prob = 0.2
        seg2.avg_logprob = -0.4

        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([seg1, seg2], MagicMock())

        with patch("backends.cpu._model", mock_model):
            from backends.cpu import transcribe

            audio = np.zeros(32000, dtype=np.float32)
            result = transcribe(audio, 16000)
            assert result.text == "hello world"
