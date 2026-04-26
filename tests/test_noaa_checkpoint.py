"""Tests for _init_noaa_checkpoint and _record_tile_complete — Task 14.

Composite PK: (catalog_snapshot, state_usps, tile_filename) ensures that
NAIP border quads shipped in both states' directories get two independent
rows, preventing the silent-dedup that the old tile_filename-only PK caused.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import _init_noaa_checkpoint, _record_tile_complete


def test_checkpoint_schema_has_composite_pk(tmp_path):
    """New checkpoint table PK = (catalog_snapshot, state_usps, tile_filename)."""
    db = tmp_path / "ckpt.sqlite"
    _init_noaa_checkpoint(db)
    con = sqlite3.connect(db)
    rows = con.execute("PRAGMA table_info(_noaa_checkpoint)").fetchall()
    names = {r[1] for r in rows}
    assert {"catalog_snapshot", "state_usps", "tile_filename"} <= names


def test_border_quad_shipped_in_two_states_both_recorded(tmp_path):
    """A filename appearing in both AZ and UT directories gets TWO rows."""
    db = tmp_path / "ckpt.sqlite"
    _init_noaa_checkpoint(db)
    _record_tile_complete(db, "snap1.json", "AZ", "m_border.tif")
    _record_tile_complete(db, "snap1.json", "UT", "m_border.tif")
    # No PK conflict
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM _noaa_checkpoint").fetchone()[0]
    assert count == 2


def test_init_noaa_checkpoint_migrates_old_schema(tmp_path):
    """If the table exists with the old PK (tile_filename only), DROP + recreate."""
    db = tmp_path / "ckpt.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE _noaa_checkpoint (tile_filename TEXT PRIMARY KEY)")
    con.execute("INSERT INTO _noaa_checkpoint VALUES ('old.tif')")
    con.commit()
    con.close()

    _init_noaa_checkpoint(db)

    con = sqlite3.connect(db)
    rows = con.execute("PRAGMA table_info(_noaa_checkpoint)").fetchall()
    names = {r[1] for r in rows}
    assert {"catalog_snapshot", "state_usps", "tile_filename"} <= names
    # Old row discarded because migration was DROP + recreate
    count = con.execute("SELECT COUNT(*) FROM _noaa_checkpoint").fetchone()[0]
    assert count == 0
    con.close()


def test_init_noaa_checkpoint_idempotent(tmp_path):
    """Calling init twice on the new schema is a no-op (no rows lost)."""
    db = tmp_path / "ckpt.sqlite"
    _init_noaa_checkpoint(db)
    _record_tile_complete(db, "snap.json", "AZ", "tile.tif")
    _init_noaa_checkpoint(db)  # second call — must not drop existing row
    con = sqlite3.connect(db)
    count = con.execute("SELECT COUNT(*) FROM _noaa_checkpoint").fetchone()[0]
    assert count == 1
