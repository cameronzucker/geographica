"""Tests for NOAA catalog resolver — mapping bbox/state to catalog entries."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import resolve_noaa_candidates, build_state_queue, build_unified_queue


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


def test_build_queue_whole_state_uses_full_index():
    """Whole-state mode should list all tiles without -spat filter."""
    entry = {"usps": "AZ", "year": 2021, "dir": "AZ_NAIP_2021_9596"}
    shp_path = Path("/fake.shp")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "filename\ntile1.tif\ntile2.tif\n"
    mock_result.stderr = ""

    with patch("scripts.acquire_imagery.subprocess.run", return_value=mock_result) as mock_run:
        result = build_state_queue(entry, None, shp_path)

    # Should be called exactly once
    assert mock_run.call_count == 1

    # Should NOT contain -spat
    call_args = mock_run.call_args[0][0]
    assert "-spat" not in call_args
    assert "-f" in call_args
    assert "CSV" in call_args
    assert str(shp_path) in call_args
    assert "-select" in call_args
    assert "filename" in call_args

    # Should parse output correctly
    assert result == ["tile1.tif", "tile2.tif"]


def test_build_queue_bbox_calls_ogr2ogr_spat_with_300s_timeout():
    """Bbox mode should call ogr2ogr with -spat and 300s timeout."""
    entry = {"usps": "AZ", "year": 2021, "dir": "AZ_NAIP_2021_9596"}
    bbox = "-112.0,35.1,-111.5,35.4"
    shp_path = Path("/fake.shp")

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "filename\ntile1.tif\ntile2.tif\n"
    mock_result.stderr = ""

    with patch("scripts.acquire_imagery.subprocess.run", return_value=mock_result) as mock_run:
        result = build_state_queue(entry, bbox, shp_path)

    # Should be called exactly once
    assert mock_run.call_count == 1

    # Should contain -spat with bbox values as separate elements
    call_args = mock_run.call_args[0][0]
    assert "-spat" in call_args
    spat_idx = call_args.index("-spat")
    assert call_args[spat_idx + 1] == "-112.0"
    assert call_args[spat_idx + 2] == "35.1"
    assert call_args[spat_idx + 3] == "-111.5"
    assert call_args[spat_idx + 4] == "35.4"

    # Should be called with timeout=300
    assert mock_run.call_args[1].get("timeout") == 300

    # Should parse output correctly
    assert result == ["tile1.tif", "tile2.tif"]


def test_build_unified_queue_produces_per_tile_tuples(tmp_path):
    snapshot = tmp_path / "snapshots" / "snap.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text("{}")

    az = {"usps": "AZ", "dir": "AZ_NAIP_2021_9596", "year": 2021,
          "tile_count": 2, "tile_index_url": "...", "tile_index_sha256": "..."}
    ut = {"usps": "UT", "dir": "UT_NAIP_2021_9601", "year": 2021,
          "tile_count": 1, "tile_index_url": "...", "tile_index_sha256": "..."}

    def fake_build_state_queue(entry, bbox, shp):
        return {"AZ": ["a1.tif", "a2.tif"], "UT": ["u1.tif"]}[entry["usps"]]

    with patch("acquire_imagery.build_state_queue", side_effect=fake_build_state_queue):
        items = build_unified_queue([az, ut], bbox_or_none=None, snapshot_path=snapshot)

    base = "https://coastalimagery.blob.core.windows.net/digitalcoast"
    assert items == [
        (snapshot, "AZ", "a1.tif", f"{base}/AZ_NAIP_2021_9596/a1.tif"),
        (snapshot, "AZ", "a2.tif", f"{base}/AZ_NAIP_2021_9596/a2.tif"),
        (snapshot, "UT", "u1.tif", f"{base}/UT_NAIP_2021_9601/u1.tif"),
    ]


def test_build_unified_queue_empty_candidates_returns_empty(tmp_path):
    assert build_unified_queue([], bbox_or_none=None, snapshot_path=tmp_path / "x.json") == []


# ---------------------------------------------------------------------------
# Task 15: pin_catalog_snapshot
# ---------------------------------------------------------------------------

def test_pin_catalog_snapshot_resolves_symlink(tmp_path):
    real_snapshot = tmp_path / "noaa_catalog_snapshots" / "2026-01-01T00:00:00Z.json"
    real_snapshot.parent.mkdir(parents=True)
    real_snapshot.write_text('{"entries": {}}')
    symlink = tmp_path / "noaa_naip_catalog.json"
    symlink.symlink_to(real_snapshot)

    from acquire_imagery import pin_catalog_snapshot
    result = pin_catalog_snapshot(tmp_path)
    assert result == real_snapshot.resolve()
    assert result.is_absolute()


def test_pin_catalog_snapshot_missing_symlink_raises(tmp_path):
    from acquire_imagery import pin_catalog_snapshot
    with pytest.raises(FileNotFoundError):
        pin_catalog_snapshot(tmp_path)


def test_pin_catalog_snapshot_dangling_symlink_raises(tmp_path):
    symlink = tmp_path / "noaa_naip_catalog.json"
    symlink.symlink_to(tmp_path / "does-not-exist.json")
    from acquire_imagery import pin_catalog_snapshot
    with pytest.raises(FileNotFoundError):
        pin_catalog_snapshot(tmp_path)


# ---------------------------------------------------------------------------
# Task 16: _resolve_or_pin_snapshot — resume-refuse semantics
# ---------------------------------------------------------------------------

def _make_snapshot(tmp_path: Path, name: str = "snap1.json") -> Path:
    """Helper: create a real snapshot file in a snapshots sub-dir."""
    snap_dir = tmp_path / "noaa_catalog_snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    snap = snap_dir / name
    snap.write_text('{"entries": {}}')
    return snap


def test_resume_with_pruned_snapshot_raises(tmp_path):
    """State file records a snapshot path that no longer exists → SnapshotPrunedError."""
    from acquire_imagery import _resolve_or_pin_snapshot, SnapshotPrunedError

    output = tmp_path / "imagery.mbtiles"
    state_path = tmp_path / ".pipeline-state.json"
    # Write state pointing at a non-existent snapshot
    import json
    state_path.write_text(json.dumps({"catalog_snapshot": str(tmp_path / "noaa_catalog_snapshots" / "gone.json")}))

    with pytest.raises(SnapshotPrunedError, match="Cannot resume"):
        _resolve_or_pin_snapshot(output, tmp_path)


def test_resume_with_existing_snapshot_reuses_it(tmp_path):
    """State file records a snapshot that still exists → returned without re-pinning."""
    from acquire_imagery import _resolve_or_pin_snapshot

    output = tmp_path / "imagery.mbtiles"
    state_path = tmp_path / ".pipeline-state.json"
    snap = _make_snapshot(tmp_path)

    import json
    state_path.write_text(json.dumps({"catalog_snapshot": str(snap)}))

    # Deliberately do NOT create the noaa_naip_catalog.json symlink;
    # if the function tried to re-pin it would raise FileNotFoundError.
    result = _resolve_or_pin_snapshot(output, tmp_path)
    assert result == snap


def test_fresh_run_pins_new_snapshot(tmp_path):
    """No state file → calls pin_catalog_snapshot, writes state, returns path."""
    from acquire_imagery import _resolve_or_pin_snapshot

    output = tmp_path / "imagery.mbtiles"
    snap = _make_snapshot(tmp_path)
    # Create the symlink that pin_catalog_snapshot reads
    symlink = tmp_path / "noaa_naip_catalog.json"
    symlink.symlink_to(snap)

    result = _resolve_or_pin_snapshot(output, tmp_path)
    assert result == snap.resolve()

    # State file must have been written with the snapshot path
    import json
    state_path = tmp_path / ".pipeline-state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["catalog_snapshot"] == str(snap.resolve())


def test_state_file_unreadable_treats_as_fresh(tmp_path):
    """Corrupt state JSON → logs warning and falls back to fresh-run pin."""
    from acquire_imagery import _resolve_or_pin_snapshot

    output = tmp_path / "imagery.mbtiles"
    state_path = tmp_path / ".pipeline-state.json"
    state_path.write_text("NOT VALID JSON {{{")

    snap = _make_snapshot(tmp_path)
    symlink = tmp_path / "noaa_naip_catalog.json"
    symlink.symlink_to(snap)

    result = _resolve_or_pin_snapshot(output, tmp_path)
    assert result == snap.resolve()
