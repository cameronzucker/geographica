"""Regression tests for the preflight 'Python pipeline deps' check.

Background: The original implementation used in-process `__import__('rasterio')`
to verify that pipeline Python packages (rasterio/shapely/scipy/numpy) are
installed. That ALWAYS returned 'missing' in production because
setup.sh runs inside `setup/.venv` — a fresh venv that does NOT inherit
the user's `~/.local/.../site-packages` where bootstrap.sh's
`pip install --user` placed those packages. Beta testers on 2026-04-19
hit this: even after rebooting, the wizard insisted dependencies were
missing and told them to re-run bootstrap in an infinite loop.

The fix shells out to `/usr/bin/python3 -c 'import <pkg>'` so the check
reflects the actual user-environment state bootstrap targeted.

These tests guard against regression — specifically:
  1. The check calls `/usr/bin/python3` explicitly (not a bare `python3`
     which would be the venv's Python).
  2. A subprocess returncode == 0 is 'ok'; non-zero is 'missing'.
  3. Each package is tested independently so a mix of
     installed/missing is reported correctly.
"""
import subprocess
from unittest.mock import patch, MagicMock

from setup.main import _check_python_pipeline_deps


def test_all_packages_importable_returns_ok():
    """Happy path: every `/usr/bin/python3 -c 'import X'` exits 0 → status ok."""
    proc = MagicMock()
    proc.returncode = 0
    with patch("setup.main.subprocess.run", return_value=proc) as run_mock:
        result = _check_python_pipeline_deps()
    assert result["status"] == "ok", result
    assert "all importable" in result["message"]
    # One subprocess call per package (4 packages).
    assert run_mock.call_count == 4


def test_all_packages_missing_returns_missing_status():
    proc = MagicMock()
    proc.returncode = 1
    with patch("setup.main.subprocess.run", return_value=proc):
        result = _check_python_pipeline_deps()
    assert result["status"] == "missing", result
    assert "Missing:" in result["message"]
    for pkg in ("rasterio", "shapely", "scipy", "numpy"):
        assert pkg in result["message"], f"{pkg} not listed as missing"


def test_only_rasterio_missing_is_reported_specifically():
    """Mix: numpy/shapely/scipy succeed, rasterio fails."""
    def fake_run(cmd, *_, **__):
        proc = MagicMock()
        # cmd[-1] is like 'import rasterio' or 'import numpy'
        proc.returncode = 1 if "import rasterio" in cmd[-1] else 0
        return proc

    with patch("setup.main.subprocess.run", side_effect=fake_run):
        result = _check_python_pipeline_deps()
    assert result["status"] == "missing", result
    assert "rasterio" in result["message"]
    for pkg in ("shapely", "scipy", "numpy"):
        assert pkg not in result["message"], \
            f"{pkg} should NOT appear as missing (it succeeded)"


def test_uses_absolute_path_to_system_python_not_venv():
    """The check MUST invoke /usr/bin/python3, not a bare `python3` — the
    latter would use the setup/.venv interpreter, which doesn't have
    access to the user's `~/.local/...` where bootstrap installed the
    packages. This is the exact regression that blocked beta testers
    for weeks."""
    captured_commands = []

    def fake_run(cmd, *_, **__):
        captured_commands.append(cmd)
        proc = MagicMock()
        proc.returncode = 0
        return proc

    with patch("setup.main.subprocess.run", side_effect=fake_run):
        _check_python_pipeline_deps()

    assert len(captured_commands) == 4, captured_commands
    for cmd in captured_commands:
        # first arg must be the ABSOLUTE path to system python
        assert cmd[0] == "/usr/bin/python3", (
            f"preflight must use /usr/bin/python3 (not a bare 'python3' "
            f"which would resolve to the venv interpreter and miss "
            f"packages installed via `pip install --user`). Got: {cmd[0]}"
        )
        assert cmd[1] == "-c"
        assert cmd[2].startswith("import ")


def test_subprocess_timeout_reports_package_missing():
    """If subprocess.run raises TimeoutExpired, the package is reported as
    missing rather than propagating the exception (which would become a
    500 response from /api/preflight and display a raw traceback in the
    wizard UI — exactly the 'large spaghetti GUI errors' beta tester
    report)."""
    def fake_run(cmd, *_, **__):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=10)

    with patch("setup.main.subprocess.run", side_effect=fake_run):
        result = _check_python_pipeline_deps()
    assert result["status"] == "missing", result
    # All four packages reported missing (since all four timed out).
    for pkg in ("rasterio", "shapely", "scipy", "numpy"):
        assert pkg in result["message"], f"{pkg} not listed"


def test_file_not_found_on_python_executable_reports_missing():
    """If /usr/bin/python3 doesn't exist on the target system (highly
    unusual but possible on minimal images), the check reports the
    package as missing rather than raising."""
    def fake_run(cmd, *_, **__):
        raise FileNotFoundError(f"no such file: {cmd[0]}")

    with patch("setup.main.subprocess.run", side_effect=fake_run):
        result = _check_python_pipeline_deps()
    assert result["status"] == "missing", result
