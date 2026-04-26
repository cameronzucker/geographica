"""Enforcement: raw tile-table writes outside designated wrappers.

The incremental overview design (spec 2026-04-22) depends on every
base-tile mutation going through _mutate_base_tile (single-tile) or
merge_mbtiles's bulk SQL block. A raw INSERT/UPDATE/DELETE elsewhere
would silently break the dirty-tracking invariant.

This test greps for violations — cheap safety net, not foolproof.
Designated wrappers: rasterio_ops._mutate_base_tile,
acquire_imagery.merge_mbtiles (bulk), _drain_journal, _drain_nuclear,
_init_noaa_checkpoint (SQLite schema for a different table).
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent

# Files allowed to contain raw 'INTO tiles' or 'UPDATE tiles' or
# 'FROM tiles' writes. Each entry is (file, allowed-function-context-keyword).
ALLOWED_SITES = {
    "scripts/rasterio_ops.py": [
        "_mutate_base_tile",       # the designated per-tile helper
        "_drain_journal",           # writes composited ancestors
        "_drain_nuclear",           # writes composited ancestors
        "_composite_2x2_children",  # reads only
        "_bulk_import_tiles",       # fresh-MBTiles import path (rasterio→MBTiles);
                                    # output is merged into NOAA MBTiles via
                                    # merge_mbtiles downstream, which populates
                                    # the journal at that boundary.
    ],
    "scripts/acquire_imagery.py": [
        "merge_mbtiles",            # bulk path (wrapped in BEGIN/COMMIT)
        "convert_batch_to_mbtiles",  # temp-MBTiles creation; caller pipelines
                                     # the result through merge_mbtiles, which
                                     # is the journal-boundary function.
    ],
}

# Pattern matches: INSERT INTO tiles, INSERT OR IGNORE/REPLACE INTO tiles,
# UPDATE tiles, DELETE FROM tiles (case-insensitive, whitespace-tolerant)
WRITE_PATTERN = re.compile(
    r"""
    (?:INSERT\s+(?:OR\s+(?:IGNORE|REPLACE)\s+)?INTO\s+tiles\b)
    | (?:UPDATE\s+tiles\b)
    | (?:DELETE\s+FROM\s+tiles\b)
    """,
    re.IGNORECASE | re.VERBOSE,
)


def test_no_raw_tile_writes_outside_designated_wrappers():
    """Scan the NOAA-relevant files for writes to the tiles table. Each
    match must be inside a function listed in ALLOWED_SITES for that file."""
    violations = []

    for rel_path, allowed_funcs in ALLOWED_SITES.items():
        path = REPO_ROOT / rel_path
        assert path.exists(), f"{rel_path} not found — update ALLOWED_SITES"
        source = path.read_text()
        # Build a map of line-number → containing top-level function name
        func_by_line = {}
        current_func = None
        for i, line in enumerate(source.splitlines(), 1):
            match = re.match(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", line)
            if match:
                current_func = match.group(1)
            func_by_line[i] = current_func

        # Find all writes
        for match in WRITE_PATTERN.finditer(source):
            # Compute line number
            line_num = source[:match.start()].count("\n") + 1
            containing_func = func_by_line.get(line_num)
            if containing_func not in allowed_funcs:
                violations.append(
                    f"{rel_path}:{line_num}  in {containing_func!r}: "
                    f"{match.group(0)!r}"
                )

    assert not violations, (
        "Raw tile-table writes found outside designated wrappers:\n"
        + "\n".join("  " + v for v in violations)
        + "\n\nAll base-tile writes must go through _mutate_base_tile "
        "or merge_mbtiles's bulk block so the journal stays complete. "
        "Add the function to ALLOWED_SITES if it's a legitimate new "
        "wrapper, otherwise refactor it to use _mutate_base_tile."
    )
