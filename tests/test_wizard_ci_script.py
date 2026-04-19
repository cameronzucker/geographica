import os
from pathlib import Path
SCRIPT = Path(__file__).parent.parent / "dev" / "harness" / "wizard-ci.sh"


def test_script_exists_and_executable():
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK)


def test_script_uses_lxc_launch():
    text = SCRIPT.read_text()
    assert "lxc launch" in text
    assert "images:debian/trixie/cloud" in text or "debian/trixie" in text


def test_script_waits_for_setup_port():
    text = SCRIPT.read_text()
    assert "8099" in text
    assert "curl" in text or "wget" in text


def test_script_invokes_drive_wizard_mjs():
    text = SCRIPT.read_text()
    assert "drive-wizard.mjs" in text


def test_script_accepts_smoke_or_full():
    text = SCRIPT.read_text()
    assert "--smoke" in text
    assert "--full" in text


def test_script_exits_with_status_on_health_check():
    text = SCRIPT.read_text()
    assert "exit 0" in text or 'exit "$RC"' in text or "exit $RC" in text
