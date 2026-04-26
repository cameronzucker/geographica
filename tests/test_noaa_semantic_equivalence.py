"""Phase 6 Task 38 — NOAA Arizona whole-state semantic-equivalence regression.

Asserts that a post-refactor NOAA Arizona run produces an MBTiles that is
semantically equivalent to a pre-refactor baseline. Equivalence is NOT
byte-for-byte (MBTiles carries timestamps, WAL state, and rendering-order
differences that don't affect map output). Equivalence is:

1. Tile count per zoom level matches.
2. Metadata keys match (values may differ on name/description).
3. SHA256 hash of the raw tile blob matches for a 10-point sample grid
   across the state's extent at a mid-range zoom.

Usage
-----
Run with both MBTiles paths set via env vars:

    GEOGRAPHICA_NOAA_BASELINE_MBTILES=/path/to/baseline.mbtiles \\
    GEOGRAPHICA_NOAA_CURRENT_MBTILES=/path/to/current.mbtiles \\
    python -m pytest tests/test_noaa_semantic_equivalence.py -v

If either env var is unset or the file is missing, the tests skip — this
keeps CI green on machines without the real 39 GB baseline.

Capturing a baseline
--------------------
From a pre-refactor branch tip (no worktrees — banned):

    git checkout <pre-refactor-sha>
    python scripts/acquire_imagery.py --mode noaa --state arizona \\
        --bbox=-114.82,31.33,-109.05,37.00 \\
        --output /srv/geographica/data/noaa_az_baseline.mbtiles

Then return to the current branch and run the same invocation with a
different output path; point the env vars at the two MBTiles.
"""
import hashlib
import os
import sqlite3
from pathlib import Path

import pytest


BASELINE_ENV = "GEOGRAPHICA_NOAA_BASELINE_MBTILES"
CURRENT_ENV = "GEOGRAPHICA_NOAA_CURRENT_MBTILES"


def _skip_if_missing():
    baseline = os.environ.get(BASELINE_ENV)
    current = os.environ.get(CURRENT_ENV)
    if not baseline:
        pytest.skip(f"{BASELINE_ENV} not set")
    if not current:
        pytest.skip(f"{CURRENT_ENV} not set")
    if not Path(baseline).exists():
        pytest.skip(f"{baseline} does not exist on disk")
    if not Path(current).exists():
        pytest.skip(f"{current} does not exist on disk")
    return Path(baseline), Path(current)


def _tile_count_by_zoom(mbtiles_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT zoom_level, COUNT(*) FROM tiles GROUP BY zoom_level ORDER BY zoom_level"
        ).fetchall()
        return {z: c for z, c in rows}
    finally:
        conn.close()


def _metadata_keys(mbtiles_path: Path) -> set:
    conn = sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True)
    try:
        rows = conn.execute("SELECT name FROM metadata").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def _sample_grid_tile_coords(min_zoom: int, max_zoom: int) -> list:
    """Return a stable list of (zoom_level, tile_column, tile_row) tuples
    that span the state's typical coverage. These are the probe points
    we'll hash on both sides.

    Arizona 2021 NOAA imagery is z17 native + overview pyramids down to
    z0. Use z15 for the sample grid (widely populated, reasonable blob
    size). The exact tile coordinates are state-dependent but for AZ
    2021 the bbox (-114.82, 31.33, -109.05, 37.00) maps to z15 tile
    ranges roughly x in [5050, 5450], y in [12400, 12850].
    """
    z = 15
    coords = [
        (z,  5100, 12500),   # NW corner
        (z,  5400, 12500),   # NE corner
        (z,  5100, 12800),   # SW corner
        (z,  5400, 12800),   # SE corner
        (z,  5250, 12650),   # center
        (z,  5150, 12600),   # NW quadrant
        (z,  5350, 12600),   # NE quadrant
        (z,  5150, 12750),   # SW quadrant
        (z,  5350, 12750),   # SE quadrant
        (z,  5250, 12500),   # north edge
    ]
    return [c for c in coords if min_zoom <= c[0] <= max_zoom]


def _tile_hash(mbtiles_path: Path, z: int, x: int, y: int) -> "str | None":
    conn = sqlite3.connect(f"file:{mbtiles_path}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
            (z, x, y),
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return hashlib.sha256(row[0]).hexdigest()
    finally:
        conn.close()


def test_tile_count_by_zoom_matches():
    """Same tiles produced per zoom level."""
    baseline, current = _skip_if_missing()
    baseline_counts = _tile_count_by_zoom(baseline)
    current_counts = _tile_count_by_zoom(current)
    assert baseline_counts == current_counts, (
        f"Tile-count-by-zoom mismatch\n"
        f"  baseline: {baseline_counts}\n"
        f"  current:  {current_counts}"
    )


def test_metadata_keys_match():
    """Same metadata rows present (values may legitimately differ: name, version)."""
    baseline, current = _skip_if_missing()
    baseline_keys = _metadata_keys(baseline)
    current_keys = _metadata_keys(current)
    # Allow current to have a strict SUPERSET (refactor may add fields) but
    # not remove anything.
    missing = baseline_keys - current_keys
    assert not missing, (
        f"Metadata keys missing from current run: {missing}\n"
        f"  baseline: {sorted(baseline_keys)}\n"
        f"  current:  {sorted(current_keys)}"
    )


def test_sample_grid_tile_hashes_match():
    """SHA256 hash of raw tile blob matches for 10 probe coordinates.

    Post-refactor should produce byte-identical tiles because the 3-stage
    pipeline, reprojection params, and merge ordering are all unchanged —
    only the catalog-lookup + queue-build preamble was restructured.
    """
    baseline, current = _skip_if_missing()
    baseline_counts = _tile_count_by_zoom(baseline)
    if not baseline_counts:
        pytest.skip("baseline has no tiles")
    min_zoom, max_zoom = min(baseline_counts), max(baseline_counts)
    probes = _sample_grid_tile_coords(min_zoom, max_zoom)

    mismatches = []
    missing = []
    for z, x, y in probes:
        bh = _tile_hash(baseline, z, x, y)
        ch = _tile_hash(current, z, x, y)
        if bh is None and ch is None:
            missing.append((z, x, y))
            continue
        if bh is None or ch is None:
            mismatches.append((z, x, y, "one side missing"))
            continue
        if bh != ch:
            mismatches.append((z, x, y, f"hash {bh[:12]} vs {ch[:12]}"))

    # If more than half the probes land on empty tiles, the coord grid is
    # wrong for this state — skip rather than false-pass.
    if len(missing) > len(probes) / 2:
        pytest.skip(
            f"Probe grid didn't hit tile data: {len(missing)}/{len(probes)} "
            f"tiles missing from both MBTiles. Adjust _sample_grid_tile_coords "
            f"for this state's extent."
        )

    assert not mismatches, (
        f"Sample-grid tile hashes differ:\n" +
        "\n".join(f"  z={z} x={x} y={y}: {why}" for z, x, y, why in mismatches)
    )
