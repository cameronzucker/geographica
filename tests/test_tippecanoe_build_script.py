import os
from pathlib import Path
REPO = Path(__file__).parent.parent
SCRIPT = REPO / "tools" / "build-tippecanoe.sh"


def test_script_exists():
    assert SCRIPT.exists()


def test_script_is_executable():
    assert os.access(SCRIPT, os.X_OK)


def test_script_references_version_and_arch():
    text = SCRIPT.read_text()
    assert "TIPPECANOE_VERSION" in text
    assert "aarch64" in text or "arm64" in text


def test_script_produces_tarball():
    text = SCRIPT.read_text()
    assert "tippecanoe-" in text and ".tar.gz" in text


def test_readme_documents_release_cut():
    readme = REPO / "tools" / "README.md"
    assert readme.exists()
    assert "gh release" in readme.read_text()
