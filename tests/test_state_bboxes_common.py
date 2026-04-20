"""Regression tests for the extracted scripts/common/state_bboxes.py primitive.

Must preserve byte-parity with the old setup/runner.py implementation. These
tests deliberately mirror the old setup-side tests so if the extraction
drops behavior, a setup-side test will also fail and we catch it here first.
"""
import pytest
from scripts.common.state_bboxes import (
    STATE_BBOXES,
    states_intersecting,
)


def test_state_bboxes_has_all_48_contiguous_plus_dc():
    assert len(STATE_BBOXES) >= 49
    assert "district-of-columbia" in STATE_BBOXES
    assert "arizona" in STATE_BBOXES
    assert "georgia-us" in STATE_BBOXES


def test_states_intersecting_arizona_bbox():
    result = states_intersecting("-112.0,35.1,-111.5,35.4")
    assert result == ["arizona"]


def test_states_intersecting_four_corners():
    result = states_intersecting("-109.1,36.9,-108.9,37.1")
    assert set(result) == {"arizona", "colorado", "new-mexico", "utah"}


def test_states_intersecting_malformed_returns_empty():
    assert states_intersecting("not,a,bbox") == []
    assert states_intersecting("") == []
    assert states_intersecting("1,2,3") == []


def test_states_intersecting_outside_all_states_returns_empty():
    # Middle of the Atlantic
    assert states_intersecting("-50.0,30.0,-49.0,31.0") == []


def test_backward_compat_underscore_alias():
    # setup/runner.py callers use _states_intersecting (underscore prefix).
    # New code uses states_intersecting (no prefix). Shim must preserve both.
    from scripts.common.state_bboxes import _states_intersecting
    assert _states_intersecting("-112.0,35.1,-111.5,35.4") == ["arizona"]
