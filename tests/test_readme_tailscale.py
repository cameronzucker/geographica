from pathlib import Path
README = Path(__file__).parent.parent / "README.md"


def test_tailscale_uses_sed_not_append():
    text = README.read_text()
    idx = text.find("## HTTPS via Tailscale")
    assert idx != -1, "Could not find '## HTTPS via Tailscale' section in README"
    section = text[idx:idx + 1200]
    assert 'echo "TLS_MODE=tailscale" >> .env' not in section
    assert "sed -i" in section or "sed -E" in section
