"""Shared pytest fixtures for STT service tests."""

import io
import struct
from pathlib import Path

import numpy as np
import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def wav_bytes_factory():
    """Factory fixture that creates valid WAV byte buffers.

    Usage:
        wav = wav_bytes_factory(duration_s=2.0, sample_rate=16000)
    """

    def _make_wav(
        duration_s: float = 2.0,
        sample_rate: int = 16000,
        num_channels: int = 1,
        bits_per_sample: int = 16,
    ) -> bytes:
        num_samples = int(duration_s * sample_rate)
        # Generate silence (zeros)
        samples = np.zeros(num_samples, dtype=np.int16)
        raw_data = samples.tobytes()

        byte_rate = sample_rate * num_channels * (bits_per_sample // 8)
        block_align = num_channels * (bits_per_sample // 8)
        data_size = len(raw_data)

        buf = io.BytesIO()
        # RIFF header
        buf.write(b"RIFF")
        buf.write(struct.pack("<I", 36 + data_size))
        buf.write(b"WAVE")
        # fmt chunk
        buf.write(b"fmt ")
        buf.write(struct.pack("<I", 16))  # chunk size
        buf.write(struct.pack("<H", 1))  # PCM format
        buf.write(struct.pack("<H", num_channels))
        buf.write(struct.pack("<I", sample_rate))
        buf.write(struct.pack("<I", byte_rate))
        buf.write(struct.pack("<H", block_align))
        buf.write(struct.pack("<H", bits_per_sample))
        # data chunk
        buf.write(b"data")
        buf.write(struct.pack("<I", data_size))
        buf.write(raw_data)

        return buf.getvalue()

    return _make_wav
