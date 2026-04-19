"""Verify nginx/entrypoint.sh aliases deprecated TLS_MODE values to canonical ones."""
import subprocess
from pathlib import Path

ENTRYPOINT = Path(__file__).parent.parent / "nginx" / "entrypoint.sh"


def test_deprecated_aliases_present():
    text = ENTRYPOINT.read_text()
    assert "self-signed)" in text
    assert "external)" in text
    assert "existing)" in text
    # Each deprecation should emit a WARN line
    assert text.count("WARN: TLS_MODE=") >= 3


def test_self_signed_aliased_to_https():
    text = ENTRYPOINT.read_text()
    # Find the self-signed branch, ensure it reassigns TLS_MODE=https
    idx = text.find("self-signed)")
    assert idx > 0
    # Look at the next ~200 chars for the assignment
    snippet = text[idx:idx+300]
    assert "TLS_MODE=https" in snippet


def test_external_aliased_to_tailscale():
    text = ENTRYPOINT.read_text()
    idx = text.find("external)")
    assert idx > 0
    snippet = text[idx:idx+300]
    assert "TLS_MODE=tailscale" in snippet
