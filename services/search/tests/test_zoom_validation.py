"""Tests for _parse_zoom validation changes.

Verifies zoom 19 is accepted (M2M max) and zoom 20 is rejected.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import _parse_zoom


def test_zoom_19_accepted():
    """M2M maximum zoom 19 should be accepted."""
    result = _parse_zoom("0-19")
    assert result == (0, 19)


def test_zoom_18_still_accepted():
    """Existing zoom 18 should still be accepted (regression check)."""
    result = _parse_zoom("0-18")
    assert result == (0, 18)


def test_zoom_20_rejected():
    """Zoom 20 is beyond max supported and should be rejected."""
    with pytest.raises(ValueError, match="0-19"):
        _parse_zoom("0-20")


def test_zoom_0_accepted():
    """Zoom 0-0 is valid (minimum)."""
    result = _parse_zoom("0-0")
    assert result == (0, 0)


def test_zoom_negative_rejected():
    """Negative zoom values should be rejected."""
    with pytest.raises(ValueError):
        _parse_zoom("-1-10")


def test_zoom_min_greater_than_max_rejected():
    """Min > max should be rejected."""
    with pytest.raises(ValueError):
        _parse_zoom("10-5")
