from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_symlink_uses_force_no_deref_and_guards_real_dir():
    text = BOOTSTRAP.read_text()
    assert "ln -sfn" in text
    assert 'exists as a regular directory' in text or \
           'Remove it manually before re-running bootstrap' in text


def test_no_recursive_chown_of_srv_root():
    text = BOOTSTRAP.read_text()
    assert "chown -R \"$ACTUAL_USER\":\"$ACTUAL_USER\" /srv/geographica" not in text
