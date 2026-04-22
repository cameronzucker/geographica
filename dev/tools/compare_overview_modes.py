#!/usr/bin/env python3
"""A/B comparison harness — nuclear vs journal overview rebuild.

Usage:
    python3 dev/tools/compare_overview_modes.py /path/to/source.mbtiles

Snapshots the input MBTiles into two clones via SQLite backup (with WAL
checkpoint), runs build_overviews(mode="nuclear") on clone A and
build_overviews(mode="journal") on clone B, compares outputs, and
prints wall-time + semantic-equivalence report.

Does NOT modify the source. Produces two .mbtiles files in /tmp/ that
are cleaned up on successful exit.
"""
import argparse
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
from rasterio.io import MemoryFile

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from rasterio_ops import build_overviews  # noqa: E402


def clone_mbtiles(src: Path, dst: Path) -> None:
    """Clone with WAL checkpoint + .backup API (R5 I3)."""
    # First: force WAL checkpoint so .backup sees the latest committed state.
    ck = sqlite3.connect(str(src))
    try:
        ck.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        ck.close()

    # Now: sqlite3's backup API copies the snapshot-consistent pages.
    src_conn = sqlite3.connect(str(src))
    dst_conn = sqlite3.connect(str(dst))
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()


def compare_outputs(path_a: Path, path_b: Path) -> dict:
    """Compare coord sets + pixel diff. Returns a report dict."""
    conn_a = sqlite3.connect(str(path_a))
    conn_b = sqlite3.connect(str(path_b))
    try:
        coords_a = set(conn_a.execute(
            "SELECT zoom_level, tile_column, tile_row FROM tiles"
        ).fetchall())
        coords_b = set(conn_b.execute(
            "SELECT zoom_level, tile_column, tile_row FROM tiles"
        ).fetchall())

        only_a = coords_a - coords_b
        only_b = coords_b - coords_a
        common = coords_a & coords_b

        # Sample up to 200 common tiles for pixel diff (full scan is slow on
        # large MBTiles)
        sample = list(common)[:200]
        diffs = []
        mismatches = []
        for (z, tc, tr) in sample:
            data_a = conn_a.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, tc, tr),
            ).fetchone()[0]
            data_b = conn_b.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, tc, tr),
            ).fetchone()[0]
            try:
                with MemoryFile(data_a) as mf:
                    arr_a = mf.open().read()
                with MemoryFile(data_b) as mf:
                    arr_b = mf.open().read()
                diff = float(np.abs(arr_a.astype(np.int16) - arr_b.astype(np.int16)).mean())
                diffs.append(diff)
                if diff >= 2.0:
                    mismatches.append(((z, tc, tr), diff))
            except Exception as exc:
                mismatches.append(((z, tc, tr), f"decode error: {exc}"))

        return {
            "count_a": len(coords_a),
            "count_b": len(coords_b),
            "only_a": only_a,
            "only_b": only_b,
            "common": len(common),
            "sampled": len(sample),
            "max_diff": max(diffs) if diffs else 0.0,
            "avg_diff": sum(diffs) / len(diffs) if diffs else 0.0,
            "mismatches": mismatches,
        }
    finally:
        conn_a.close()
        conn_b.close()


def seed_journal_from_base_tiles(path: Path) -> int:
    """Populate _overview_work_queue with the full ancestor lineage of every
    base tile at max_zoom. Used when the input MBTiles has an empty queue
    (e.g., built by legacy nuclear code) so the journal path has meaningful
    work to do for the A/B comparison.

    Returns the count of (z, tc, tr) rows inserted. Idempotent — repeated
    calls are collapsed by the queue's PK.
    """
    from rasterio_ops import _init_journal  # noqa: E402
    conn = sqlite3.connect(str(path))
    try:
        _init_journal(conn)
        max_zoom_row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
        if not max_zoom_row or max_zoom_row[0] is None:
            return 0
        max_zoom = max_zoom_row[0]
        conn.execute("BEGIN")
        for dz in range(1, max_zoom + 1):
            conn.execute(
                """INSERT OR IGNORE INTO _overview_work_queue
                   (zoom_level, tile_column, tile_row)
                   SELECT zoom_level - ?, tile_column >> ?, tile_row >> ?
                   FROM tiles WHERE zoom_level = ?""",
                (dz, dz, dz, max_zoom),
            )
        conn.execute("COMMIT")
        return conn.execute("SELECT COUNT(*) FROM _overview_work_queue").fetchone()[0]
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Compare overview modes on an MBTiles.")
    parser.add_argument("source", type=Path, help="Input MBTiles file")
    parser.add_argument("--out-dir", type=Path, default=Path("/tmp"),
                        help="Directory for clones (default: /tmp)")
    parser.add_argument("--keep", action="store_true",
                        help="Keep clone files after comparison")
    parser.add_argument(
        "--seed-journal", action="store_true",
        help="Before running journal drain on clone B, enqueue the full "
             "ancestor lineage of every base tile at max_zoom. Use this "
             "when the source has an empty _overview_work_queue (e.g. a "
             "legacy MBTiles or one built before Task 8 shipped). Without "
             "this flag, journal mode on an empty queue is a no-op and "
             "the comparison is meaningless.",
    )
    args = parser.parse_args()

    if not args.source.exists():
        print(f"Source not found: {args.source}", file=sys.stderr)
        return 1

    clone_a = args.out_dir / "overview_compare_nuclear.mbtiles"
    clone_b = args.out_dir / "overview_compare_journal.mbtiles"

    print(f"Cloning {args.source} → {clone_a}")
    clone_mbtiles(args.source, clone_a)
    print(f"Cloning {args.source} → {clone_b}")
    clone_mbtiles(args.source, clone_b)

    # Diagnostic: what does the queue look like on each clone?
    for label, path in [("A (nuclear)", clone_a), ("B (journal)", clone_b)]:
        _dc = sqlite3.connect(str(path))
        try:
            _dc.execute(
                "CREATE TABLE IF NOT EXISTS _overview_work_queue ("
                "zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, "
                "PRIMARY KEY (zoom_level, tile_column, tile_row))"
            )
            _qc = _dc.execute("SELECT COUNT(*) FROM _overview_work_queue").fetchone()[0]
            print(f"Clone {label} journal rows: {_qc}")
        finally:
            _dc.close()

    if args.seed_journal:
        seeded = seed_journal_from_base_tiles(clone_b)
        print(f"Seeded clone B journal with {seeded} ancestor rows at max_zoom lineage")

    print("Running nuclear drain on clone A...")
    t0 = time.monotonic()
    build_overviews(clone_a, mode="nuclear")
    t_nuclear = time.monotonic() - t0

    print("Running journal drain on clone B...")
    t0 = time.monotonic()
    build_overviews(clone_b, mode="journal")
    t_journal = time.monotonic() - t0

    print("Comparing outputs...")
    report = compare_outputs(clone_a, clone_b)

    print()
    print("=== RESULT ===")
    print(f"Nuclear wall-time:  {t_nuclear:6.2f} s")
    print(f"Journal wall-time:  {t_journal:6.2f} s")
    print(f"Speedup:            {t_nuclear / t_journal:.1f}x")
    print(f"Tile counts:        nuclear={report['count_a']}  journal={report['count_b']}")
    print(f"Only-in-nuclear:    {len(report['only_a'])}")
    print(f"Only-in-journal:    {len(report['only_b'])}")
    print(f"Common tiles:       {report['common']}")
    print(f"Sampled for diff:   {report['sampled']}")
    print(f"Max pixel diff:     {report['max_diff']:.3f}")
    print(f"Avg pixel diff:     {report['avg_diff']:.3f}")
    print(f"Mismatches (>2.0):  {len(report['mismatches'])}")

    if report['mismatches']:
        print("\nFirst 5 mismatches:")
        for m in report['mismatches'][:5]:
            print(f"  {m}")

    ok = (
        len(report['only_a']) == 0
        and len(report['only_b']) == 0
        and report['max_diff'] < 2.0
    )

    if not args.keep:
        clone_a.unlink(missing_ok=True)
        clone_b.unlink(missing_ok=True)

    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
