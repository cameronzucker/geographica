"""Verify no cdzucker typos in docs or scripts."""
from pathlib import Path

REPO = Path(__file__).parent.parent


def test_readme_has_no_cdzucker():
    text = (REPO / "README.md").read_text()
    assert "cdzucker" not in text


def test_bootstrap_has_no_cdzucker():
    text = (REPO / "bootstrap.sh").read_text()
    assert "cdzucker" not in text


def test_readme_has_no_code_geographica_devpath():
    text = (REPO / "README.md").read_text()
    assert "~/Code/geographica" not in text


def test_correct_clone_url_appears():
    text = (REPO / "README.md").read_text()
    assert "github.com/cameronzucker/geographica" in text
