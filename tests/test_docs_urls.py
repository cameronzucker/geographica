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


def test_verify_deployment_section_uses_nginx_proxy():
    text = (REPO / "README.md").read_text()
    start = text.find("## 12.")
    assert start != -1
    end = text.find("\n## ", start + 1)
    section = text[start:end] if end != -1 else text[start:]
    forbidden = [
        "http://localhost:8090",
        "http://localhost:8092",
        "http://localhost:8094",
        "http://localhost:8095",
        "http://localhost:8096",
        "http://localhost:8098",
    ]
    for url in forbidden:
        assert url not in section, f"§12 must use :8093 proxy, found: {url}"
    assert "http://localhost:8093/" in section


def test_readme_manual_section_is_labeled_advanced():
    text = (REPO / "README.md").read_text()
    assert "Manual setup (advanced" in text
    assert "setup wizard" in text.lower()
