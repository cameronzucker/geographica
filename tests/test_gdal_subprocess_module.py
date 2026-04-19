"""Tests for the extracted scripts/gdal_subprocess.py helper."""

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestGdalSubprocessModule:
    """Verify the extracted module exists and behaves correctly."""

    def test_module_importable(self):
        import gdal_subprocess
        assert hasattr(gdal_subprocess, "run_gdal_subprocess")

    def test_run_completes_on_success(self):
        import gdal_subprocess
        # `true` returns 0 instantly
        result = gdal_subprocess.run_gdal_subprocess(["true"], timeout=10)
        assert result.returncode == 0

    def test_raises_on_nonzero_exit(self):
        import gdal_subprocess
        # `false` returns 1
        with pytest.raises(subprocess.CalledProcessError):
            gdal_subprocess.run_gdal_subprocess(["false"], timeout=10)

    def test_cancel_check_before_start_raises(self):
        import gdal_subprocess
        with pytest.raises(subprocess.CalledProcessError):
            gdal_subprocess.run_gdal_subprocess(
                ["true"], timeout=10,
                cancel_check=lambda: True,
            )

    def test_on_child_started_callback_fires(self):
        import gdal_subprocess
        captured_pids = []

        def _cb(pid):
            captured_pids.append(pid)

        gdal_subprocess.run_gdal_subprocess(
            ["true"], timeout=10,
            on_child_started=_cb,
        )
        assert len(captured_pids) == 1
        assert captured_pids[0] > 0

    def test_acquire_imagery_imports_from_module(self):
        """acquire_imagery.run_gdal_subprocess must still be callable (re-exported or imported)."""
        import acquire_imagery
        assert callable(acquire_imagery.run_gdal_subprocess)

    def test_acquire_naip_uses_shared_helper(self):
        """acquire_naip should no longer use `subprocess.run(..., check=True, ...` for GDAL commands."""
        import inspect
        import acquire_naip
        src = inspect.getsource(acquire_naip)
        # Count old blocking-subprocess.run call sites that still have check=True on gdal commands
        # The 4 original sites had lines like: subprocess.run([..., "gdal_translate", ...], check=True, ...)
        # After the fix, those should be replaced by run_gdal_subprocess calls.
        # We assert the import exists AND the naive subprocess.run-on-gdal pattern is reduced.
        assert "from gdal_subprocess import run_gdal_subprocess" in src \
            or "import gdal_subprocess" in src, \
            "acquire_naip.py should import the shared helper"

        # Count remaining "subprocess.run(" occurrences — the fix replaces 4 call sites.
        remaining = src.count("subprocess.run(")
        assert remaining <= 1, (
            f"Expected ≤1 remaining subprocess.run in acquire_naip.py (original: 4); "
            f"got {remaining}"
        )
