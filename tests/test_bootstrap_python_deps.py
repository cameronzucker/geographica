from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_bootstrap_installs_pipeline_python_deps():
    text = BOOTSTRAP.read_text()
    assert "scripts/requirements.txt" in text
    assert "pip install" in text
    assert 'sudo -u "$ACTUAL_USER"' in text
    assert "--break-system-packages" in text
    # Must use -H so HOME is set to the target user's home, otherwise
    # `pip install --user` installs into root's home directory.
    assert 'sudo -u "$ACTUAL_USER" -H' in text or \
           'sudo -H -u "$ACTUAL_USER"' in text
