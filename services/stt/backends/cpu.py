"""CPU backend using faster-whisper (CTranslate2) with INT8 quantization.

Model: base.en (~140MB)
Expected latency: ~3s for 5s audio on Pi 5 ARM (after warmup)
First inference after startup: ~5s (CTranslate2 warmup)
"""

import time

import numpy as np
from faster_whisper import WhisperModel

from backends import TranscribeResult

# Module-level model reference — loaded once at startup, reused for all requests
_model: WhisperModel | None = None

# Thresholds for filtering silence/noise hallucinations.
# Higher no_speech_threshold = more aggressively filter silent segments.
# Lower log_prob_threshold = more aggressively filter low-confidence segments.
NO_SPEECH_THRESHOLD = 0.8
LOG_PROB_THRESHOLD = -0.8


def load_model(model_path: str) -> None:
    """Load the Whisper model into memory.

    Called once at startup. The model stays in memory for the process lifetime.

    Args:
        model_path: Path to the CTranslate2 model directory
                    (e.g., "/opt/models/faster-whisper-base.en")
    """
    global _model
    _model = WhisperModel(model_path, device="cpu", compute_type="int8")


def transcribe(audio_pcm: np.ndarray, sample_rate: int) -> TranscribeResult:
    """Transcribe 16kHz mono PCM audio to text.

    Args:
        audio_pcm: Float32 numpy array of audio samples
        sample_rate: Sample rate (must be 16000)

    Returns:
        TranscribeResult with transcribed text and inference duration

    Raises:
        RuntimeError: If model is not loaded (load_model not called)
    """
    if _model is None:
        raise RuntimeError("Model not loaded. Call load_model() first.")

    start = time.monotonic()

    segments, _info = _model.transcribe(
        audio_pcm,
        language="en",
        beam_size=1,  # greedy decoding — fastest
        vad_filter=True,
    )

    # Collect text from segments that pass quality thresholds
    texts = []
    for segment in segments:
        # Filter hallucinated text from silence/noise
        if segment.no_speech_prob > NO_SPEECH_THRESHOLD:
            continue
        if segment.avg_logprob < LOG_PROB_THRESHOLD:
            continue
        texts.append(segment.text.strip())

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return TranscribeResult(
        text=" ".join(texts).strip(),
        duration_ms=elapsed_ms,
    )
