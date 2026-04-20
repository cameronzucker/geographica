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


def test_slug_by_usps_covers_all_50_states_plus_dc():
    from scripts.common.state_bboxes import SLUG_BY_USPS
    assert len(SLUG_BY_USPS) == 51  # 50 states + DC
    assert SLUG_BY_USPS["AZ"] == "arizona"
    assert SLUG_BY_USPS["GA"] == "georgia-us"
    assert SLUG_BY_USPS["DC"] == "district-of-columbia"
    assert SLUG_BY_USPS["AK"] is None  # intentionally unsupported
    assert SLUG_BY_USPS["HI"] is None


def test_usps_by_slug_round_trips_supported_states():
    from scripts.common.state_bboxes import SLUG_BY_USPS, USPS_BY_SLUG
    for usps, slug in SLUG_BY_USPS.items():
        if slug is None:
            continue
        assert USPS_BY_SLUG[slug] == usps


def test_usps_by_slug_keys_match_state_bboxes():
    from scripts.common.state_bboxes import USPS_BY_SLUG, STATE_BBOXES
    assert set(USPS_BY_SLUG.keys()) == set(STATE_BBOXES.keys())


def test_display_name_handles_all_slugs():
    from scripts.common.state_bboxes import display_name, STATE_BBOXES
    assert display_name("arizona") == "Arizona"
    assert display_name("georgia-us") == "Georgia"  # strip -us suffix
    assert display_name("district-of-columbia") == "District of Columbia"
    assert display_name("new-hampshire") == "New Hampshire"
    # Every slug in STATE_BBOXES must be renderable
    for slug in STATE_BBOXES:
        assert display_name(slug)  # no exceptions, non-empty string
