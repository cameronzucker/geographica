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
    assert "uname -m" in text  # the actual arch-detection call, not just string refs


def test_script_produces_tarball():
    import re
    text = SCRIPT.read_text()
    assert re.search(r"tar\s+-czf.*tippecanoe-.*\.tar\.gz", text), \
        "Expected a 'tar -czf … tippecanoe-*.tar.gz' line in the build script"


def test_readme_documents_release_cut():
    readme = REPO / "tools" / "README.md"
    assert readme.exists()
    assert "gh release" in readme.read_text()
