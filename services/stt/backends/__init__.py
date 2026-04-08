"""STT backend interface.

Both CPU and NPU backends implement the same contract:
- load_model(model_path: str) -> None
- transcribe(audio_pcm: np.ndarray, sample_rate: int) -> TranscribeResult
"""

from dataclasses import dataclass


@dataclass
class TranscribeResult:
    """Result from a transcription backend."""

    text: str
    duration_ms: int
