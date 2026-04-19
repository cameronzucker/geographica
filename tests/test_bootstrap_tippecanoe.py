from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_bootstrap_fetches_tippecanoe_release():
    text = BOOTSTRAP.read_text()
    assert "TIPPECANOE_RELEASE_URL" in text
    assert "github.com/cameronzucker/geographica/releases" in text
    # Allow either curl -fL or wget -q as the download mechanism
    assert "curl -fL" in text or "wget -q" in text


def test_bootstrap_installs_to_usr_local_bin():
    assert "/usr/local/bin/tippecanoe" in BOOTSTRAP.read_text()


def test_bootstrap_tippecanoe_has_fallback_message():
    assert "build-tippecanoe.sh" in BOOTSTRAP.read_text()


def _extract_tippecanoe_release_url():
    """Pull TIPPECANOE_RELEASE_URL from bootstrap.sh."""
    import re
    m = re.search(r'TIPPECANOE_RELEASE_URL="([^"]+)"', BOOTSTRAP.read_text())
    assert m, "TIPPECANOE_RELEASE_URL not found in bootstrap.sh"
    return m.group(1)


def test_tippecanoe_release_url_is_reachable():
    """Confirms the release asset uploaded via gh release upload exists.
    If this fails, see Task 9 pre-dispatch — operator must upload the binary."""
    import urllib.request
    url = _extract_tippecanoe_release_url()
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as resp:
        assert resp.status in (200, 302), f"Release asset not reachable: {url} (HTTP {resp.status})"
