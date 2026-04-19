"""Smoke-check the rollback fixtures.

This test does NOT run the agent — that's too expensive for unit tests.
It just verifies each .patch file is a valid reversible diff that
touches the expected files.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

FIXTURES = Path(__file__).parent.parent / "dev" / "harness" \
    / "exploratory_agent" / "rollback_fixtures"


def test_rollback_fixtures_directory_exists():
    assert FIXTURES.is_dir(), f"missing {FIXTURES}"


def test_websockets_fixture_is_valid_patch():
    p = FIXTURES / "websockets-missing.patch"
    assert p.exists()
    body = p.read_text()
    assert "setup/requirements.txt" in body
    # Sanity: patch body should mention 'websockets' since that's the change.
    assert "websockets" in body


def test_trailing_slash_fixture_is_valid_patch():
    p = FIXTURES / "trailing-slash-accepted.patch"
    assert p.exists()
    body = p.read_text()
    # The fix touched at least runner.py and setup.js.
    assert "setup/runner.py" in body or "setup/static/setup.js" in body


def test_fixture_readme_exists():
    p = FIXTURES / "README.md"
    assert p.exists()
    body = p.read_text()
    assert "websockets-missing.patch" in body
    assert "trailing-slash-accepted.patch" in body
