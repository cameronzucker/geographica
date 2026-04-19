import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
REPO = Path(__file__).parent.parent
INDEX_HTML = REPO / "setup" / "static" / "index.html"
ENTRYPOINT = REPO / "nginx" / "entrypoint.sh"

CANONICAL = {"http", "https", "tailscale"}


def _ui_values():
    text = INDEX_HTML.read_text()
    sel = re.search(r'<select id="tls-mode">(.*?)</select>', text, re.DOTALL)
    assert sel
    return set(re.findall(r'value="([^"]+)"', sel.group(1)))


def _nginx_values():
    text = ENTRYPOINT.read_text()
    return set(re.findall(r'\[\s*"\$TLS_MODE"\s*=\s*"([^"]+)"\s*\]', text))


def test_ui_values_are_canonical():
    assert _ui_values() <= CANONICAL


def test_ui_values_subset_of_nginx():
    ui = _ui_values() - {"http"}
    assert ui <= _nginx_values()


def test_generate_env_roundtrip():
    from setup.config import generate_env, RAM_PROFILE_16GB
    for mode in CANONICAL:
        env = generate_env(
            tls_mode=mode, ram_profile=RAM_PROFILE_16GB,
            bbox="-124.8,31.3,-102.0,49.0",
            data_path="/srv/geographica/data",
            scripts_path="/home/pi/geographica/scripts",
            tls_cert_dir="/srv/geographica/tls",
            tls_port=443, stt_backend="cpu",
        )
        assert f"TLS_MODE={mode}" in env


def test_generate_env_emits_exactly_one_tls_mode():
    """Structural assertion: exactly one TLS_MODE line, with the right value.
    Prevents the 'substring passes but two lines are present' class of bugs."""
    from setup.config import generate_env, RAM_PROFILE_16GB
    for mode in ("http", "https", "tailscale"):
        env = generate_env(
            tls_mode=mode, bbox="0,0,1,1",
            data_path="/srv/geographica/data",
            scripts_path="/home/administrator/Code/geographica/scripts",
            ram_profile=RAM_PROFILE_16GB,
        )
        tls_lines = [l for l in env.splitlines() if l.startswith("TLS_MODE=")]
        assert tls_lines == [f"TLS_MODE={mode}"], f"expected exactly one TLS_MODE={mode} line, got {tls_lines}"
