"""Geographica STT Service -- Offline Whisper speech-to-text.

Provides POST /transcribe and GET /health endpoints.
NGINX proxies /stt/* to this service, stripping the prefix.

Backend selection via STT_BACKEND environment variable:
  - "cpu" (default): faster-whisper with CTranslate2 INT8
  - "npu": HailoRT on Hailo 10H (requires /dev/hailo0)
"""

import io
import logging
import os
import struct
import time
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
STT_BACKEND = os.environ.get("STT_BACKEND", "cpu")
MODEL_PATH = os.environ.get("MODEL_PATH", "/data/models")
BAKED_MODEL_PATH = "/opt/models/faster-whisper-base.en"

# Limits
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB
MAX_DURATION_S = 15.0
MIN_DURATION_S = 0.5
REQUIRED_SAMPLE_RATE = 16000
REQUIRED_CHANNELS = 1
REQUIRED_BITS = 16

# Module-level backend reference -- set during startup
_backend = None
_backend_name = STT_BACKEND


# ---------------------------------------------------------------------------
# WAV parsing
# ---------------------------------------------------------------------------
def _parse_wav_header(data: bytes) -> dict:
    """Parse WAV file header and return format info.

    Args:
        data: Raw bytes of the WAV file

    Returns:
        Dict with keys: sample_rate, num_channels, bits_per_sample,
        data_offset, data_size, num_samples, duration_s

    Raises:
        ValueError: If the file is not a valid WAV
    """
    if len(data) < 44:
        raise ValueError("File too small to be a valid WAV")

    riff = data[0:4]
    wave = data[8:12]
    if riff != b"RIFF" or wave != b"WAVE":
        raise ValueError("Not a valid WAV file (missing RIFF/WAVE header)")

    # Find fmt chunk
    offset = 12
    fmt_found = False
    sample_rate = 0
    num_channels = 0
    bits_per_sample = 0

    while offset < len(data) - 8:
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]

        if chunk_id == b"fmt ":
            if chunk_size < 16:
                raise ValueError("Invalid fmt chunk size")
            audio_format = struct.unpack_from("<H", data, offset + 8)[0]
            if audio_format != 1:
                raise ValueError(
                    f"Unsupported audio format {audio_format} (must be PCM=1)"
                )
            num_channels = struct.unpack_from("<H", data, offset + 10)[0]
            sample_rate = struct.unpack_from("<I", data, offset + 12)[0]
            bits_per_sample = struct.unpack_from("<H", data, offset + 22)[0]
            fmt_found = True

        if chunk_id == b"data":
            if not fmt_found:
                raise ValueError("data chunk before fmt chunk")
            data_size = chunk_size
            data_offset = offset + 8
            bytes_per_sample = bits_per_sample // 8
            num_samples = data_size // (num_channels * bytes_per_sample)
            duration_s = num_samples / sample_rate if sample_rate > 0 else 0

            return {
                "sample_rate": sample_rate,
                "num_channels": num_channels,
                "bits_per_sample": bits_per_sample,
                "data_offset": data_offset,
                "data_size": data_size,
                "num_samples": num_samples,
                "duration_s": duration_s,
            }

        offset += 8 + chunk_size
        # Chunks must be word-aligned
        if chunk_size % 2 != 0:
            offset += 1

    raise ValueError("No data chunk found in WAV file")


def _wav_to_float32(data: bytes, header: dict) -> np.ndarray:
    """Extract PCM audio from WAV and convert to float32.

    Args:
        data: Raw WAV file bytes
        header: Parsed WAV header dict from _parse_wav_header

    Returns:
        Float32 numpy array of audio samples, normalized to [-1.0, 1.0]
    """
    start = header["data_offset"]
    end = start + header["data_size"]
    raw = data[start:end]

    samples = np.frombuffer(raw, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


# ---------------------------------------------------------------------------
# Lifespan -- load model at startup
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the STT model at startup."""
    global _backend, _backend_name

    _backend_name = os.environ.get("STT_BACKEND", "cpu")

    if _backend_name == "npu":
        from backends import npu as backend_mod
    else:
        from backends import cpu as backend_mod

    _backend = backend_mod

    # Determine model path: prefer MODEL_PATH env var, fall back to baked-in
    model_path = os.environ.get("MODEL_PATH", "")
    if _backend_name == "cpu":
        # For CPU: look for model dir at MODEL_PATH/faster-whisper-base.en
        # or fall back to baked-in path
        candidate = os.path.join(model_path, "faster-whisper-base.en")
        if model_path and os.path.isdir(candidate):
            effective_path = candidate
        else:
            effective_path = BAKED_MODEL_PATH
    else:
        effective_path = model_path

    logger.info("Loading STT model: backend=%s, path=%s", _backend_name, effective_path)

    try:
        _backend.load_model(effective_path)
        logger.info("STT model loaded successfully")
    except Exception as e:
        logger.error("Failed to load STT model: %s", e)
        raise

    yield

    logger.info("STT service shutting down")


app = FastAPI(title="Geographica STT", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Health check endpoint."""
    npu_available = False
    try:
        from backends.npu import detect_hardware

        npu_available = detect_hardware()
    except ImportError:
        pass

    return {
        "status": "ok",
        "backend": _backend_name,
        "model": "base.en",
        "npu_available": npu_available,
    }


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    """Transcribe audio from a WAV file upload.

    Request: multipart/form-data with field "audio" containing a WAV file.

    The WAV must be:
    - 16kHz sample rate
    - Mono (1 channel)
    - 16-bit PCM
    - <= 1 MB file size

    Returns:
        200: {"text": "...", "backend": "cpu", "duration_ms": 1234}
        200: {"text": "", "reason": "no_speech"|"too_short", ...}
        413: File too large
        422: Invalid WAV format
    """
    # Read the entire file
    data = await audio.read()

    # Check file size
    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File size {len(data)} exceeds limit of {MAX_FILE_SIZE} bytes",
        )

    # Parse and validate WAV header
    try:
        header = _parse_wav_header(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if header["sample_rate"] != REQUIRED_SAMPLE_RATE:
        raise HTTPException(
            status_code=422,
            detail=f"Sample rate must be {REQUIRED_SAMPLE_RATE}Hz, got {header['sample_rate']}Hz",
        )

    if header["num_channels"] != REQUIRED_CHANNELS:
        raise HTTPException(
            status_code=422,
            detail=f"Must be mono ({REQUIRED_CHANNELS} channel), got {header['num_channels']} channels",
        )

    if header["bits_per_sample"] != REQUIRED_BITS:
        raise HTTPException(
            status_code=422,
            detail=f"Must be {REQUIRED_BITS}-bit PCM, got {header['bits_per_sample']}-bit",
        )

    # Duration checks
    duration_s = header["duration_s"]

    if duration_s < MIN_DURATION_S:
        return {
            "text": "",
            "reason": "too_short",
            "backend": _backend_name,
            "duration_ms": 0,
        }

    # Extract audio samples
    audio_pcm = _wav_to_float32(data, header)

    # Truncate if too long
    truncated = False
    max_samples = int(MAX_DURATION_S * REQUIRED_SAMPLE_RATE)
    if len(audio_pcm) > max_samples:
        audio_pcm = audio_pcm[:max_samples]
        truncated = True

    # Transcribe
    if _backend is None:
        raise HTTPException(status_code=503, detail="STT backend not loaded")

    try:
        result = _backend.transcribe(audio_pcm, REQUIRED_SAMPLE_RATE)
    except NotImplementedError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(
            status_code=503, detail=f"Inference failed: {e}"
        )

    response = {
        "text": result.text,
        "backend": _backend_name,
        "duration_ms": result.duration_ms,
    }

    if not result.text:
        response["reason"] = "no_speech"

    if truncated:
        response["truncated"] = True

    return response
