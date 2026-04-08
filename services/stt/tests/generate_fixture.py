"""Generate a synthetic test WAV file for STT tests.

Creates a 2-second WAV file at 16kHz, mono, 16-bit PCM
containing a 440Hz sine wave (not real speech, but valid audio
that exercises the full pipeline).

For real speech tests, replace this with a recorded WAV.
Run once: python tests/generate_fixture.py
"""

import io
import struct
import sys
from pathlib import Path

import numpy as np


def generate_test_wav(output_path: Path, duration_s: float = 2.0) -> None:
    """Generate a synthetic 16kHz mono WAV file.

    Args:
        output_path: Where to save the WAV file
        duration_s: Duration in seconds
    """
    sample_rate = 16000
    num_samples = int(duration_s * sample_rate)

    # Generate a 440Hz sine wave
    t = np.linspace(0, duration_s, num_samples, endpoint=False, dtype=np.float32)
    samples = (np.sin(2 * np.pi * 440 * t) * 0.5 * 32767).astype(np.int16)

    raw_data = samples.tobytes()
    data_size = len(raw_data)

    buf = io.BytesIO()
    # RIFF header
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    # fmt chunk
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))       # PCM
    buf.write(struct.pack("<H", 1))       # mono
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * 2))  # byte rate
    buf.write(struct.pack("<H", 2))       # block align
    buf.write(struct.pack("<H", 16))      # bits per sample
    # data chunk
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(raw_data)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(buf.getvalue())
    print(f"Generated {output_path} ({data_size + 44} bytes, {duration_s}s)")


if __name__ == "__main__":
    fixture_path = Path(__file__).parent / "fixtures" / "test_audio.wav"
    generate_test_wav(fixture_path)
