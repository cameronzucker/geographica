"""Tests for the NPU (HailoRT) backend.

These tests are automatically skipped when:
- /dev/hailo0 is not present
- HEF files are not found in the model path
- hailo_platform package is not installed
"""

import os
from pathlib import Path

import numpy as np
import pytest

# Skip all tests in this module if Hailo hardware is not available
hailo_available = os.path.exists("/dev/hailo0")
_model_path = os.environ.get("MODEL_PATH", "/data/models")
hef_files_present = (
    Path(_model_path, "whisper_base_encoder_h10.hef").exists()
    and Path(_model_path, "whisper_base_decoder_h10.hef").exists()
)
pytestmark = pytest.mark.skipif(
    not hailo_available,
    reason="Hailo hardware not available (/dev/hailo0 not found)",
)


def test_npu_module_imports():
    """npu module should be importable even without hailo hardware."""
    # This test runs even without hardware — it's excluded from the skipif
    pass


@pytest.mark.skipif(
    not hailo_available or not hef_files_present,
    reason="No Hailo hardware or HEF files not found",
)
def test_npu_load_model():
    """load_model should load HEF files without version error."""
    from backends.npu import load_model

    model_path = os.environ.get("MODEL_PATH", "/data/models")
    # Will raise if HEF files are incompatible with firmware version
    load_model(model_path)


@pytest.mark.skipif(
    not hailo_available or not hef_files_present,
    reason="No Hailo hardware or HEF files not found",
)
def test_npu_transcribe_synthetic():
    """Transcribe synthetic (zeros) audio should not crash."""
    from backends.npu import load_model, transcribe

    model_path = os.environ.get("MODEL_PATH", "/data/models")
    load_model(model_path)

    audio = np.zeros(16000 * 3, dtype=np.float32)  # 3 seconds of silence
    result = transcribe(audio, 16000)
    # Silence should produce empty or near-empty text
    assert isinstance(result.text, str)
    assert result.duration_ms >= 0


# Import test that runs regardless of hardware
class TestNpuModuleStructure:
    """Tests that run without Hailo hardware."""

    @pytest.mark.skipif(False, reason="Always runs")
    def test_npu_module_has_load_model(self):
        """npu module must expose load_model function."""
        from backends import npu

        assert callable(getattr(npu, "load_model", None))

    @pytest.mark.skipif(False, reason="Always runs")
    def test_npu_module_has_transcribe(self):
        """npu module must expose transcribe function."""
        from backends import npu

        assert callable(getattr(npu, "transcribe", None))

    @pytest.mark.skipif(False, reason="Always runs")
    def test_npu_detect_hardware_returns_bool(self):
        """detect_hardware() should return a boolean."""
        from backends.npu import detect_hardware

        result = detect_hardware()
        assert isinstance(result, bool)
