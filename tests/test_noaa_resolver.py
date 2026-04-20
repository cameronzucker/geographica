"""Tests for NOAA catalog resolver — mapping bbox/state to catalog entries."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import resolve_noaa_candidates


SAMPLE_CATALOG = {
    "entries": {
        "arizona": {"usps": "AZ", "year": 2021, "dir": "AZ_NAIP_2021_9596", "tile_count": 50124,
                    "tile_index_url": "...", "tile_index_sha256": "..."},
        "utah":    {"usps": "UT", "year": 2021, "dir": "UT_NAIP_2021_9601", "tile_count": 28451,
                    "tile_index_url": "...", "tile_index_sha256": "..."},
    }
}


def test_resolve_state_mode_returns_single_entry():
    candidates, missing = resolve_noaa_candidates(SAMPLE_CATALOG, state="arizona", bbox=None)
    assert [c["usps"] for c in candidates] == ["AZ"]
    assert missing == []


def test_resolve_bbox_mode_returns_intersecting():
    # Four Corners bbox
    candidates, missing = resolve_noaa_candidates(
        SAMPLE_CATALOG, state=None, bbox="-109.1,36.9,-108.9,37.1"
    )
    assert {c["usps"] for c in candidates} == {"AZ", "UT"}
    # Colorado and New Mexico not in SAMPLE_CATALOG → missing[]
    assert set(missing) == {"colorado", "new-mexico"}


def test_resolve_state_mode_uncataloged_raises():
    with pytest.raises(ValueError, match="wyoming not in catalog"):
        resolve_noaa_candidates(SAMPLE_CATALOG, state="wyoming", bbox=None)
