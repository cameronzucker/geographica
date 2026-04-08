"""NPU backend using HailoRT on Hailo 10H.

This is a skeleton implementation. The actual HEF files for Whisper on H10
are compiled for firmware 5.2.0; the Pi 5's hailo-10-all package is currently
at 5.1.1. This code is ready for when the firmware catches up.

HEF files expected at MODEL_PATH:
  - whisper_base_encoder_h10.hef
  - whisper_base_decoder_h10.hef

Inference flow:
  1. Mel spectrogram: computed on CPU (numpy) from 16kHz PCM
  2. Encoder: mel -> encoder hidden states (NPU)
  3. Decoder: autoregressive token generation (NPU per token, greedy on CPU)
"""

import logging
import os
import time
from pathlib import Path

import numpy as np

from backends import TranscribeResult

logger = logging.getLogger(__name__)

_encoder = None
_decoder = None
_vdevice = None


def detect_hardware() -> bool:
    """Check if Hailo hardware is available.

    Returns:
        True if /dev/hailo0 exists (device is present)
    """
    return os.path.exists("/dev/hailo0")


def load_model(model_path: str) -> None:
    """Load Whisper HEF files for NPU inference.

    Expects two HEF files in model_path:
      - whisper_base_encoder_h10.hef
      - whisper_base_decoder_h10.hef

    Args:
        model_path: Directory containing HEF files

    Raises:
        FileNotFoundError: If HEF files are not found
        RuntimeError: If HEF files are incompatible with firmware version
    """
    global _encoder, _decoder, _vdevice

    model_dir = Path(model_path)
    encoder_path = model_dir / "whisper_base_encoder_h10.hef"
    decoder_path = model_dir / "whisper_base_decoder_h10.hef"

    if not encoder_path.exists():
        raise FileNotFoundError(f"Encoder HEF not found: {encoder_path}")
    if not decoder_path.exists():
        raise FileNotFoundError(f"Decoder HEF not found: {decoder_path}")

    try:
        from hailo_platform import HEF, VDevice

        _vdevice = VDevice()
        _encoder = HEF(str(encoder_path))
        _decoder = HEF(str(decoder_path))

        logger.info("Loaded Whisper HEF files for NPU inference")
        logger.info("Encoder: %s", encoder_path)
        logger.info("Decoder: %s", decoder_path)

    except ImportError:
        raise RuntimeError(
            "hailo_platform package not installed. "
            "Install it or use STT_BACKEND=cpu."
        )
    except Exception as e:
        raise RuntimeError(f"Failed to load HEF files: {e}")


def _compute_mel_spectrogram(audio_pcm: np.ndarray, sample_rate: int) -> np.ndarray:
    """Compute 80-bin log-mel spectrogram from PCM audio.

    This runs on CPU. The output feeds into the NPU encoder.

    Args:
        audio_pcm: Float32 numpy array of audio samples at 16kHz
        sample_rate: Must be 16000

    Returns:
        numpy array of shape (1, 80, n_frames) -- mel spectrogram
    """
    # TODO: Implement mel spectrogram computation
    # Use numpy FFT + mel filterbank (no librosa dependency)
    # Parameters: 400-sample window, 160-sample hop, 80 mel bins, 16kHz
    raise NotImplementedError(
        "Mel spectrogram computation not yet implemented. "
        "Waiting for HEF compatibility testing."
    )


def transcribe(audio_pcm: np.ndarray, sample_rate: int) -> TranscribeResult:
    """Transcribe 16kHz mono PCM audio to text using NPU.

    Args:
        audio_pcm: Float32 numpy array of audio samples
        sample_rate: Sample rate (must be 16000)

    Returns:
        TranscribeResult with transcribed text and inference duration

    Raises:
        RuntimeError: If model is not loaded or NPU inference fails
    """
    if _encoder is None or _decoder is None:
        raise RuntimeError("Model not loaded. Call load_model() first.")

    start = time.monotonic()

    try:
        # Step 1: Compute mel spectrogram on CPU
        mel = _compute_mel_spectrogram(audio_pcm, sample_rate)

        # Step 2: Run encoder on NPU
        # TODO: Configure infer_model from _encoder HEF
        # encoder_output = infer_model.run(mel)

        # Step 3: Run decoder on NPU (autoregressive, greedy)
        # TODO: Implement token-by-token decoding
        # tokens = greedy_decode(encoder_output, _decoder)

        # Step 4: Detokenize
        # TODO: Use tiktoken with Whisper vocabulary
        # text = detokenize(tokens)

        raise NotImplementedError(
            "NPU inference pipeline not yet implemented. "
            "Waiting for HEF compatibility testing."
        )

    except NotImplementedError:
        raise
    except Exception as e:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.error("NPU inference failed after %dms: %s", elapsed_ms, e)
        raise RuntimeError(f"NPU inference failed: {e}")
