# Unified Imagery Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the z15-z17 imagery gap, add an imagery catalog API endpoint, and make roads/labels readable over overlay imagery.

**Architecture:** Three independent components: (1) fix the existing gdaladdo call in the NOAA pipeline to be cancellable and add metadata fixup so TileServer reports correct zoom bounds, (2) add a catalog endpoint that queries actual MBTiles tile data to report what imagery exists at what zoom levels, (3) add dynamic paint overrides to switch road/label styling when overlay imagery is visible.

**Tech Stack:** Python (scripts, FastAPI), SQLite, MapLibre GL JS, GDAL CLI

**Spec:** `docs/superpowers/specs/2026-04-15-unified-imagery-layer-design.md`

---

## File Map

| File | Role | Tasks |
|------|------|-------|
| `scripts/acquire_imagery.py` | NOAA pipeline: gdaladdo fix + metadata fixup | 1 |
| `tests/test_noaa_naip.py` | Tests for gdaladdo + metadata fixup | 1 |
| `services/search/main.py` | Imagery catalog endpoint | 2 |
| `tests/test_imagery_catalog.py` | Tests for catalog endpoint | 2 |
| `frontend/app.js` | Paint overrides + catalog-driven source discovery | 3 |

**Cross-task dependencies:** Tasks 1, 2, and 3 are independent and can run in parallel. No shared file modifications between tasks.

---

## Task 1: Fix gdaladdo Cancel Support + Add Metadata Fixup

**Files:**
- Modify: `scripts/acquire_imagery.py:1842-1850` (replace subprocess.run with run_gdal_subprocess, add metadata fixup)
- Modify: `tests/test_noaa_naip.py` (add tests)

BEFORE starting work:
1. Read the skill at `.claude/skills/test-driven-development/` (or invoke /test-driven-development)
2. Read `docs/pitfalls/testing-pitfalls.md`
3. Read `dev/testing-pitfalls.md`
Follow TDD: write failing test -> implement fix -> verify green.

**Context:** `run_noaa()` in `scripts/acquire_imagery.py` already calls `gdaladdo` at lines 1842-1848. Two bugs:
- It uses `subprocess.run()` instead of `run_gdal_subprocess()`, so SIGTERM during the 2-hour overview generation can't kill the child process.
- After gdaladdo adds z15-z17 tiles, the MBTiles metadata table still says `minzoom=18`. TileServer reads this on startup and tells MapLibre not to request tiles below z18, so the z15-z17 gap persists despite the overview tiles existing.

`run_gdal_subprocess()` is defined at line 598. It uses `Popen` with `os.setsid()` for process group management, sets `_child_pid` for the SIGTERM handler, and accepts a `cancel_check` callable.

The `_NOAA_GDAL_ENV` dict at line 1508 sets `GDAL_CACHEMAX=256` and `GDAL_NUM_THREADS=2`. Currently the existing `subprocess.run()` call passes this as `env=_NOAA_GDAL_ENV`. But `run_gdal_subprocess()` at line 621 constructs its own env with `GDAL_CACHEMAX` from `os.environ`. The NOAA call needs to pass the correct env.

**WARNING (Pitfall #11 — subprocess.run blocking signal handlers):** The entire point of this fix is to replace `subprocess.run()` which blocks SIGTERM. `run_gdal_subprocess()` uses `Popen` with periodic `proc.communicate(timeout=...)` checks, allowing the cancel callback to fire. Do NOT revert to `subprocess.run()`.

**WARNING (Pitfall #16 — call-site-before-implementation):** `run_gdal_subprocess` already exists at line 598. Do NOT create a new function. Import is not needed — it's in the same file.

- [ ] **Step 1: Write test for gdaladdo cancel support**

Add to `tests/test_noaa_naip.py`:

```python
class TestGdaladdoCancelSupport:
    """Verify gdaladdo uses run_gdal_subprocess for cancel support."""

    @patch("acquire_imagery.run_gdal_subprocess")
    @patch("acquire_imagery.update_progress")
    def test_gdaladdo_uses_run_gdal_subprocess(self, mock_progress, mock_gdal):
        """Phase 5 must call run_gdal_subprocess, not subprocess.run."""
        import sqlite3, tempfile
        with tempfile.NamedTemporaryFile(suffix=".mbtiles", delete=False) as f:
            db_path = f.name
        # Create a minimal MBTiles with one z18 tile
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))")
        conn.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('minzoom', '18')")
        conn.execute("INSERT INTO metadata VALUES ('maxzoom', '18')")
        conn.execute("INSERT INTO tiles VALUES (18, 1, 1, X'00')")
        conn.commit()
        conn.close()

        try:
            from acquire_imagery import _run_gdaladdo_with_metadata_fixup
            _run_gdaladdo_with_metadata_fixup(Path(db_path))

            # Verify run_gdal_subprocess was called (not subprocess.run)
            mock_gdal.assert_called_once()
            cmd = mock_gdal.call_args[0][0]
            assert "gdaladdo" in cmd
            assert "-r" in cmd
            assert "average" in cmd
        finally:
            Path(db_path).unlink(missing_ok=True)
```

- [ ] **Step 2: Write test for metadata fixup**

Add to `tests/test_noaa_naip.py`:

```python
class TestMetadataFixup:
    """Verify metadata is updated after gdaladdo."""

    @patch("acquire_imagery.run_gdal_subprocess")
    def test_metadata_updated_after_gdaladdo(self, mock_gdal):
        """After gdaladdo, minzoom/maxzoom must reflect actual tile data."""
        import sqlite3, tempfile
        with tempfile.NamedTemporaryFile(suffix=".mbtiles", delete=False) as f:
            db_path = f.name
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))")
        conn.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('minzoom', '18')")
        conn.execute("INSERT INTO metadata VALUES ('maxzoom', '18')")
        # Simulate tiles at z15 and z18 (as if gdaladdo already ran)
        conn.execute("INSERT INTO tiles VALUES (15, 1, 1, X'00')")
        conn.execute("INSERT INTO tiles VALUES (16, 2, 2, X'00')")
        conn.execute("INSERT INTO tiles VALUES (18, 8, 8, X'00')")
        conn.commit()
        conn.close()

        try:
            from acquire_imagery import _run_gdaladdo_with_metadata_fixup
            _run_gdaladdo_with_metadata_fixup(Path(db_path))

            conn = sqlite3.connect(db_path)
            minzoom = conn.execute("SELECT value FROM metadata WHERE name='minzoom'").fetchone()[0]
            maxzoom = conn.execute("SELECT value FROM metadata WHERE name='maxzoom'").fetchone()[0]
            conn.close()
            assert minzoom == "15", f"Expected minzoom=15, got {minzoom}"
            assert maxzoom == "18", f"Expected maxzoom=18, got {maxzoom}"
        finally:
            Path(db_path).unlink(missing_ok=True)

    @patch("acquire_imagery.run_gdal_subprocess")
    def test_metadata_fixup_skipped_on_cancel(self, mock_gdal):
        """If cancel is requested, metadata should NOT be updated."""
        import sqlite3, tempfile, acquire_imagery
        with tempfile.NamedTemporaryFile(suffix=".mbtiles", delete=False) as f:
            db_path = f.name
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))")
        conn.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('minzoom', '18')")
        conn.execute("INSERT INTO metadata VALUES ('maxzoom', '18')")
        conn.execute("INSERT INTO tiles VALUES (15, 1, 1, X'00')")
        conn.execute("INSERT INTO tiles VALUES (18, 8, 8, X'00')")
        conn.commit()
        conn.close()

        original = acquire_imagery._cancel_requested
        try:
            acquire_imagery._cancel_requested = True
            from acquire_imagery import _run_gdaladdo_with_metadata_fixup
            _run_gdaladdo_with_metadata_fixup(Path(db_path))

            conn = sqlite3.connect(db_path)
            minzoom = conn.execute("SELECT value FROM metadata WHERE name='minzoom'").fetchone()[0]
            conn.close()
            # Should stay at 18 because cancel was requested
            assert minzoom == "18", f"Metadata should not update on cancel, got minzoom={minzoom}"
        finally:
            acquire_imagery._cancel_requested = original
            Path(db_path).unlink(missing_ok=True)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_noaa_naip.py::TestGdaladdoCancelSupport -v && python -m pytest tests/test_noaa_naip.py::TestMetadataFixup -v`

Expected: FAIL with `ImportError: cannot import name '_run_gdaladdo_with_metadata_fixup'`

- [ ] **Step 4: Implement _run_gdaladdo_with_metadata_fixup**

In `scripts/acquire_imagery.py`, add this function AFTER the `run_gdal_subprocess` function (after line ~640, before `convert_batch_to_mbtiles`):

```python
def _run_gdaladdo_with_metadata_fixup(output: Path) -> None:
    """Run gdaladdo on MBTiles output, then fix metadata to match actual tiles.

    Uses run_gdal_subprocess() for cancel support (not subprocess.run).
    After gdaladdo adds overview tiles at lower zoom levels, updates the
    metadata table so TileServer reports correct minzoom/maxzoom in TileJSON.
    """
    if _cancel_requested:
        return

    run_gdal_subprocess(
        ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
        timeout=14400,  # 4 hours — full MBTiles overview can take 2+ hours
        cancel_check=lambda: _cancel_requested,
    )

    # Cancel guard: don't fixup metadata on partial overviews
    if _cancel_requested:
        return

    # Fix metadata to reflect actual tile zoom range
    conn = sqlite3.connect(str(output))
    try:
        conn.execute(
            "UPDATE metadata SET value = (SELECT MIN(zoom_level) FROM tiles) "
            "WHERE name = 'minzoom'"
        )
        conn.execute(
            "UPDATE metadata SET value = (SELECT MAX(zoom_level) FROM tiles) "
            "WHERE name = 'maxzoom'"
        )
        conn.commit()
    finally:
        conn.close()
```

**Important:** This function reads the module-level `_cancel_requested` variable (defined at the top of the file). It does NOT need to import it.

- [ ] **Step 5: Replace the existing subprocess.run gdaladdo call in run_noaa**

Replace lines 1842-1850 in `run_noaa()`:

**Current code (lines 1842-1850):**
```python
        try:
            subprocess.run(
                ["nice", "-n", "19", "gdaladdo", "-r", "average",
                 str(output), "2", "4", "8", "16"],
                check=True, capture_output=True, text=True,
                env=_NOAA_GDAL_ENV, timeout=3600,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("Overview generation failed: %s — output is still usable", exc)
```

**Replace with:**
```python
        try:
            _run_gdaladdo_with_metadata_fixup(output)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("Overview generation failed: %s — output is still usable", exc)
```

The `_NOAA_GDAL_ENV` is handled by `run_gdal_subprocess()` which reads `GDAL_CACHEMAX` from `os.environ`. Since the pipeline container sets `GDAL_CACHEMAX=256` in its environment (via docker-compose.yml), this is picked up automatically. The `nice -n 19` prefix is also added by `run_gdal_subprocess()` internally (line 620).

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_noaa_naip.py -v`

Expected: All tests pass, including the new `TestGdaladdoCancelSupport` and `TestMetadataFixup` classes.

- [ ] **Step 7: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=60`

Expected: 475+ tests pass. No regressions.

- [ ] **Step 8: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_noaa_naip.py
git commit -m "fix: make gdaladdo cancellable + add metadata fixup for z15-z17 gap"
```

BEFORE marking this task complete:
1. Review your tests against `docs/pitfalls/testing-pitfalls.md` and `dev/testing-pitfalls.md`
2. Verify test coverage: cancel path tested? metadata update with actual tile data tested? Error path (gdaladdo fails) still handled by existing except clause?
3. Run tests and confirm green

---

## Task 2: Imagery Catalog Endpoint

**Files:**
- Modify: `services/search/main.py` (add new endpoint)
- Create: `tests/test_imagery_catalog.py`

BEFORE starting work:
1. Read the skill at `.claude/skills/test-driven-development/` (or invoke /test-driven-development)
2. Read `docs/pitfalls/testing-pitfalls.md`
3. Read `dev/testing-pitfalls.md`
Follow TDD: write failing test -> implement fix -> verify green.

**Context:** The search service at `services/search/main.py` is a FastAPI app. Existing admin endpoints follow the pattern `@app.get("/admin/...")` with optional `dependencies=[Depends(require_config_source)]` for endpoints that should only be accessible from the admin panel. The admin panel HTML is served from `localhost:8097` (config source check).

The data directory is `/srv/geographica/data/` (mounted as `/data/` inside the search container via docker-compose.yml). MBTiles files follow the naming pattern `imagery*.mbtiles`. The TileServer config at `tileserver/config.json` lists registered sources.

**WARNING (Pitfall — SQLite concurrent access):** MBTiles files may be actively read by TileServer or written by a running pipeline. Open connections in read-only mode with `sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)`. If `SQLITE_BUSY` is raised, skip that file with a note in the response.

**WARNING (Pitfall — `log` is not defined in main.py):** All `log.error()` / `log.warning()` calls in `services/search/main.py` are dead code (see `dev/testing-pitfalls.md`). Use `print()` for diagnostics in this file.

- [ ] **Step 1: Write test for catalog endpoint — happy path**

Create `tests/test_imagery_catalog.py`:

```python
"""Tests for GET /admin/imagery/catalog endpoint."""

import json
import math
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))


def _create_test_mbtiles(path: Path, tiles: list[tuple[int, int, int]]) -> None:
    """Create a minimal MBTiles file with specified tiles (zoom, col, row)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
        "tile_row INTEGER, tile_data BLOB, "
        "PRIMARY KEY (zoom_level, tile_column, tile_row))"
    )
    conn.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('name', 'test')")
    for z, x, y in tiles:
        conn.execute(
            "INSERT INTO tiles VALUES (?, ?, ?, X'FFD8FF')", (z, x, y)
        )
    conn.commit()
    conn.close()


class TestImageryCatalog:
    def test_catalog_returns_sources(self, tmp_path):
        """Catalog endpoint returns structured data for each imagery MBTiles."""
        from main import _build_imagery_catalog

        mbtiles = tmp_path / "imagery_noaa.mbtiles"
        _create_test_mbtiles(mbtiles, [
            (18, 49513, 157094),
            (18, 49514, 157094),
            (15, 6189, 19636),
        ])

        result = _build_imagery_catalog(tmp_path)
        assert len(result) == 1
        src = result[0]
        assert src["id"] == "imagery_noaa"
        assert src["file"] == "imagery_noaa.mbtiles"
        assert src["size_bytes"] > 0
        assert len(src["zoom_levels"]) == 2

        z18 = next(z for z in src["zoom_levels"] if z["zoom"] == 18)
        assert z18["tile_count"] == 2
        z15 = next(z for z in src["zoom_levels"] if z["zoom"] == 15)
        assert z15["tile_count"] == 1

    def test_catalog_bounds_are_valid_lonlat(self, tmp_path):
        """Bounds should be valid lon/lat coordinates."""
        from main import _build_imagery_catalog

        # Phoenix-area tile at z18 (TMS coordinates)
        mbtiles = tmp_path / "imagery_noaa.mbtiles"
        _create_test_mbtiles(mbtiles, [(18, 49513, 157094)])

        result = _build_imagery_catalog(tmp_path)
        bounds = result[0]["zoom_levels"][0]["bounds_lonlat"]
        lon_min, lat_min, lon_max, lat_max = bounds
        assert -180 <= lon_min < lon_max <= 180
        assert -85 <= lat_min < lat_max <= 85

    def test_catalog_skips_non_imagery_files(self, tmp_path):
        """Only imagery*.mbtiles should be included, not elevation, southwest5, etc."""
        from main import _build_imagery_catalog

        _create_test_mbtiles(tmp_path / "imagery.mbtiles", [(14, 1, 1)])
        _create_test_mbtiles(tmp_path / "elevation.mbtiles", [(10, 1, 1)])
        _create_test_mbtiles(tmp_path / "public-lands.mbtiles", [(8, 1, 1)])

        result = _build_imagery_catalog(tmp_path)
        ids = [s["id"] for s in result]
        assert "imagery" in ids
        assert "elevation" not in ids
        assert "public-lands" not in ids

    def test_catalog_handles_busy_mbtiles(self, tmp_path):
        """If MBTiles can't be opened (locked/busy), skip it gracefully."""
        from main import _build_imagery_catalog

        _create_test_mbtiles(tmp_path / "imagery.mbtiles", [(14, 1, 1)])
        # Create a corrupt file that can't be opened as SQLite
        (tmp_path / "imagery_broken.mbtiles").write_bytes(b"not a database")

        result = _build_imagery_catalog(tmp_path)
        ids = [s["id"] for s in result]
        assert "imagery" in ids
        # broken file should be skipped, not crash the whole endpoint
        assert "imagery_broken" not in ids

    def test_catalog_empty_directory(self, tmp_path):
        """Empty data directory returns empty list."""
        from main import _build_imagery_catalog

        result = _build_imagery_catalog(tmp_path)
        assert result == []

    def test_catalog_includes_registered_flag(self, tmp_path):
        """Sources in tileserver config should have registered=True."""
        from main import _build_imagery_catalog

        _create_test_mbtiles(tmp_path / "imagery_noaa.mbtiles", [(18, 1, 1)])

        ts_config = {"data": {"imagery_noaa": {"mbtiles": "/srv/data/imagery_noaa.mbtiles"}}}
        result = _build_imagery_catalog(tmp_path, tileserver_config=ts_config)
        assert result[0]["registered"] is True

        result2 = _build_imagery_catalog(tmp_path, tileserver_config={"data": {}})
        assert result2[0]["registered"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_imagery_catalog.py -v`

Expected: FAIL with `ImportError: cannot import name '_build_imagery_catalog'`

- [ ] **Step 3: Implement _build_imagery_catalog and tile_bounds_tms**

Add to `services/search/main.py`, before the existing `@app.get("/admin/status")` endpoint (around line 710):

```python
# ---------------------------------------------------------------------------
# Imagery catalog
# ---------------------------------------------------------------------------

import math as _math

def _tile_bounds_tms(z: int, min_x: int, max_x: int, min_y: int, max_y: int) -> list[float]:
    """Convert TMS tile coordinate range to [lon_min, lat_min, lon_max, lat_max].

    MBTiles uses TMS y-axis: y=0 at south pole, y increases northward.
    """
    n = 2 ** z
    lon_min = min_x / n * 360 - 180
    lon_max = (max_x + 1) / n * 360 - 180
    lat_a = _math.degrees(_math.atan(_math.sinh(_math.pi * (1 - 2 * min_y / n))))
    lat_b = _math.degrees(_math.atan(_math.sinh(_math.pi * (1 - 2 * (max_y + 1) / n))))
    return [round(lon_min, 6), round(min(lat_a, lat_b), 6),
            round(lon_max, 6), round(max(lat_a, lat_b), 6)]


def _build_imagery_catalog(
    data_dir: Path,
    tileserver_config: dict | None = None,
) -> list[dict]:
    """Scan data_dir for imagery*.mbtiles and return structured catalog."""
    results = []
    for mbt_path in sorted(data_dir.glob("imagery*.mbtiles")):
        source_id = mbt_path.stem  # e.g., "imagery_noaa"
        try:
            conn = sqlite3.connect(
                f"file:{mbt_path}?mode=ro", uri=True, timeout=5
            )
        except sqlite3.OperationalError:
            continue  # Skip files that can't be opened

        try:
            rows = conn.execute(
                "SELECT zoom_level, COUNT(*) as tile_count, "
                "MIN(tile_column), MAX(tile_column), "
                "MIN(tile_row), MAX(tile_row) "
                "FROM tiles GROUP BY zoom_level ORDER BY zoom_level"
            ).fetchall()
        except sqlite3.DatabaseError:
            conn.close()
            continue  # Skip corrupt files

        zoom_levels = []
        for z, count, min_x, max_x, min_y, max_y in rows:
            zoom_levels.append({
                "zoom": z,
                "tile_count": count,
                "bounds_lonlat": _tile_bounds_tms(z, min_x, max_x, min_y, max_y),
            })
        conn.close()

        registered = False
        if tileserver_config and "data" in tileserver_config:
            registered = source_id in tileserver_config["data"]

        stat = mbt_path.stat()
        results.append({
            "id": source_id,
            "file": mbt_path.name,
            "size_bytes": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat() + "Z",
            "registered": registered,
            "zoom_levels": zoom_levels,
        })

    return results
```

**Note:** `sqlite3`, `Path`, and `datetime` are already imported in `main.py`. The `import math as _math` is new — add it near the top of the file with the other stdlib imports.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_imagery_catalog.py -v`

Expected: All 6 tests pass.

- [ ] **Step 5: Add the HTTP endpoint**

Add after the `_build_imagery_catalog` function:

```python
@app.get("/admin/imagery/catalog")
async def imagery_catalog():
    """Return structured catalog of all imagery MBTiles files."""
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))

    # Load TileServer config for registration check
    ts_config = None
    ts_config_path = os.environ.get("TILESERVER_CONFIG")
    if ts_config_path:
        try:
            ts_config = json.loads(Path(ts_config_path).read_text())
        except (OSError, json.JSONDecodeError):
            pass

    sources = _build_imagery_catalog(data_dir, tileserver_config=ts_config)
    return {"sources": sources}
```

- [ ] **Step 6: Write integration test for the HTTP endpoint**

Add to `tests/test_imagery_catalog.py`:

```python
from fastapi.testclient import TestClient


class TestImageryCatalogEndpoint:
    def test_endpoint_returns_200(self, tmp_path):
        """GET /admin/imagery/catalog returns 200 with sources list."""
        _create_test_mbtiles(tmp_path / "imagery.mbtiles", [(14, 1, 1)])

        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            client = TestClient(app)
            resp = client.get("/admin/imagery/catalog")

        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        assert len(data["sources"]) == 1
        assert data["sources"][0]["id"] == "imagery"
```

- [ ] **Step 7: Run all tests**

Run: `python -m pytest tests/test_imagery_catalog.py tests/test_noaa_naip.py -v`

Expected: All tests pass.

- [ ] **Step 8: Run full test suite**

Run: `python -m pytest tests/ -v --timeout=60`

Expected: 475+ tests pass. No regressions.

- [ ] **Step 9: Commit**

```bash
git add services/search/main.py tests/test_imagery_catalog.py
git commit -m "feat: add imagery catalog endpoint (GET /admin/imagery/catalog)"
```

BEFORE marking this task complete:
1. Review your tests against `docs/pitfalls/testing-pitfalls.md` and `dev/testing-pitfalls.md`
2. Verify test coverage: empty dir? corrupt file? busy file? valid bounds? registration flag?
3. Run tests and confirm green

---

## Task 3: Dynamic Hybrid Paint Overrides

**Files:**
- Modify: `frontend/app.js:805-846` (add paint override table and snapshot/restore logic to `_updateOverlayImageryState`)

BEFORE starting work:
1. Read `docs/pitfalls/testing-pitfalls.md`
2. Read `dev/testing-pitfalls.md`
3. Read `tileserver/styles/hybrid/style.local.json` to verify paint property values
4. Read `tileserver/styles/positron/style.local.json` to verify layer IDs exist

**Context:** When overlay imagery (NOAA, NAIP, etc.) is toggled on over positron or darkmatter basemap, roads and labels are invisible because they use dark-on-light colors designed for a white background. The hybrid style has appropriate colors (white/semi-transparent roads, white text with dark halos) but is a separate full style — we need to apply just its paint properties dynamically.

`_updateOverlayImageryState()` at line 812 already handles hiding conflicting basemap layers (buildings, landuse, parks) and wiring the opacity slider. We're extending it to also apply paint property overrides.

**Key paint property types (verified):**
- `line-color`: always simple string values in both positron and hybrid — safe to override directly
- `line-width`: always zoom-dependent expression objects (e.g., `{base: 1.55, stops: [[13, 2.2], [20, 22]]}`) — override table must store the full expression, not a simple number
- `text-color`, `text-halo-color`, `text-halo-width`: simple values in both styles

**Layer IDs are shared** between positron, darkmatter, and hybrid. Two tunnel layers (`tunnel_motorway_casing`, `tunnel_motorway_inner`) exist in positron but NOT in darkmatter or hybrid. Always check `map.getLayer(id)` before calling `setPaintProperty()`.

**WARNING:** Do NOT modify any code outside of the overlay imagery section (lines ~805-846). Do NOT change the hybrid checkbox handler, the opacity slider handler, or the basemap radio button handlers. Those work correctly.

- [ ] **Step 1: Add the paint override table**

Add after `_conflictingBasemapLayers` (after line 810) in `frontend/app.js`:

```javascript
  // Paint property overrides to apply when overlay imagery is visible.
  // Values taken from tileserver/styles/hybrid/style.local.json.
  // line-color: simple strings. line-width: zoom expressions. text-*: simple values.
  var _hybridPaintOverrides = [
    // Roads — white semi-transparent
    { layer: 'highway_path', prop: 'line-color', value: 'rgba(255,255,255,0.15)' },
    { layer: 'highway_minor', prop: 'line-color', value: 'rgba(255,255,255,0.35)' },
    { layer: 'highway_minor', prop: 'line-width', value: { base: 1.0, stops: [[13, 0.8], [15, 1.5], [17, 2.5], [18, 4]] } },
    { layer: 'highway_major_casing', prop: 'line-color', value: 'rgba(0,0,0,0.12)' },
    { layer: 'highway_major_inner', prop: 'line-color', value: 'rgba(255,255,255,0.35)' },
    { layer: 'highway_major_inner', prop: 'line-width', value: { base: 1.1, stops: [[13, 1.2], [15, 2.5], [18, 5]] } },
    { layer: 'highway_major_subtle', prop: 'line-color', value: 'rgba(255,255,255,0.25)' },
    { layer: 'highway_motorway_casing', prop: 'line-color', value: 'rgba(0,0,0,0.2)' },
    { layer: 'highway_motorway_casing', prop: 'line-width', value: { base: 1.2, stops: [[6, 1.5], [10, 3], [14, 5], [18, 8]] } },
    { layer: 'highway_motorway_inner', prop: 'line-color', value: 'rgba(232,166,62,0.85)' },
    { layer: 'highway_motorway_inner', prop: 'line-width', value: { base: 1.2, stops: [[6, 0.5], [10, 1.5], [14, 3], [18, 6]] } },
    { layer: 'highway_motorway_subtle', prop: 'line-color', value: 'rgba(232,166,62,0.5)' },
    { layer: 'road_pier', prop: 'line-color', value: 'rgba(255,255,255,0.1)' },
    // Labels — white text with dark halos
    { layer: 'highway_name_other', prop: 'text-color', value: '#ffffff' },
    { layer: 'highway_name_other', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'highway_name_other', prop: 'text-halo-width', value: 1.5 },
    { layer: 'highway_name_motorway', prop: 'text-color', value: '#ffffff' },
    { layer: 'highway_name_motorway', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'highway_name_motorway', prop: 'text-halo-width', value: 1.5 },
    { layer: 'place_other', prop: 'text-color', value: '#ffffff' },
    { layer: 'place_other', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'place_other', prop: 'text-halo-width', value: 1.5 },
    { layer: 'place_suburb', prop: 'text-color', value: '#ffffff' },
    { layer: 'place_suburb', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'place_suburb', prop: 'text-halo-width', value: 1.5 },
    { layer: 'place_village', prop: 'text-color', value: '#ffffff' },
    { layer: 'place_village', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'place_village', prop: 'text-halo-width', value: 1.5 },
    { layer: 'place_town', prop: 'text-color', value: '#ffffff' },
    { layer: 'place_town', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'place_town', prop: 'text-halo-width', value: 1.5 },
    { layer: 'place_city', prop: 'text-color', value: '#ffffff' },
    { layer: 'place_city', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'place_city', prop: 'text-halo-width', value: 1.5 },
    { layer: 'place_city_large', prop: 'text-color', value: '#ffffff' },
    { layer: 'place_city_large', prop: 'text-halo-color', value: 'rgba(0,0,0,0.7)' },
    { layer: 'place_city_large', prop: 'text-halo-width', value: 1.5 },
    // Water labels
    { layer: 'water_name', prop: 'text-color', value: 'rgba(255,255,255,0.8)' },
    { layer: 'water_name', prop: 'text-halo-color', value: 'rgba(0,0,0,0.5)' },
    { layer: 'water_name', prop: 'text-halo-width', value: 1.5 },
  ];

  // Snapshot of original paint values before overlay overrides were applied.
  // null when no overrides are active.
  var _savedBasemapPaint = null;
```

- [ ] **Step 2: Update _updateOverlayImageryState to apply/restore paint overrides**

Replace the `_updateOverlayImageryState` function (lines 812-846) with:

```javascript
  function _updateOverlayImageryState() {
    // Check if any overlay imagery layer is visible
    var overlayIds = ['imagery-noaa-layer', 'imagery-naip-layer',
                      'imagery-sentinel-layer', 'imagery-custom-layer'];
    var anyVisible = overlayIds.some(function(id) {
      return map.getLayer(id) &&
             map.getLayoutProperty(id, 'visibility') === 'visible';
    });

    // Show/hide opacity slider row for overlay imagery
    var opacityRow = document.getElementById('imagery-opacity-row');
    if (opacityRow && currentStyle !== 'hybrid') {
      opacityRow.classList.toggle('visible', anyVisible);
    }

    // Hide/show conflicting basemap fills
    _conflictingBasemapLayers.forEach(function(layerId) {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, 'visibility', anyVisible ? 'none' : 'visible');
      }
    });

    // Apply/restore hybrid paint overrides (only on non-hybrid basemaps)
    if (currentStyle !== 'hybrid') {
      if (anyVisible && !_savedBasemapPaint) {
        // Snapshot current paint values and apply hybrid overrides
        _savedBasemapPaint = [];
        _hybridPaintOverrides.forEach(function(o) {
          if (map.getLayer(o.layer)) {
            _savedBasemapPaint.push({
              layer: o.layer,
              prop: o.prop,
              value: map.getPaintProperty(o.layer, o.prop)
            });
            map.setPaintProperty(o.layer, o.prop, o.value);
          }
        });
      } else if (!anyVisible && _savedBasemapPaint) {
        // Restore original paint values
        _savedBasemapPaint.forEach(function(o) {
          if (map.getLayer(o.layer)) {
            map.setPaintProperty(o.layer, o.prop, o.value);
          }
        });
        _savedBasemapPaint = null;
      }
    }

    // Wire opacity slider to overlay imagery layers
    if (anyVisible) {
      var slider = document.getElementById('imagery-opacity');
      if (slider) {
        var val = parseInt(slider.value, 10) / 100;
        overlayIds.forEach(function(id) {
          if (map.getLayer(id) && map.getLayoutProperty(id, 'visibility') === 'visible') {
            map.setPaintProperty(id, 'raster-opacity', val);
          }
        });
      }
    }
  }
```

- [ ] **Step 3: Handle style.load re-apply**

In the `style.load` handler at line 143 (inside `initMap()`), add a re-apply call after `syncLayerVisibility()`:

```javascript
    map.on('style.load', function () {
      addPlaceholderSources();
      syncLayerVisibility();
      // Re-apply hybrid paint overrides if overlay imagery was active before style swap
      if (_savedBasemapPaint && currentStyle !== 'hybrid') {
        // Style swap reset all paint — take fresh snapshot and re-apply
        _savedBasemapPaint = null; // clear stale snapshot
        _updateOverlayImageryState(); // will re-snapshot + re-apply if overlays still visible
      }
      // Re-disable and re-remove dragRotate handlers after style swap
      // MapLibre resets handler state on style change — see Pitfall #11
      map.dragRotate.disable();
```

The key insight: after a style swap, `_savedBasemapPaint` holds values from the OLD style. We clear it and call `_updateOverlayImageryState()`, which will take a fresh snapshot of the NEW style's paint values and apply the hybrid overrides.

- [ ] **Step 4: Verify manually (no automated tests for frontend JS)**

Open the app in a browser:
1. Start on positron basemap
2. Toggle NOAA imagery checkbox ON
3. Verify: roads should appear white/semi-transparent, labels should have white text with dark halos
4. Toggle NOAA imagery OFF
5. Verify: roads and labels restore to positron's original dark-on-light colors
6. Switch to darkmatter basemap, toggle NOAA ON
7. Verify: overrides apply correctly on darkmatter too
8. While NOAA is ON, switch basemap from positron to darkmatter
9. Verify: overrides re-apply with darkmatter's paint values as the new snapshot base
10. Switch to hybrid mode (Hybrid checkbox)
11. Verify: no overlay paint overrides applied (hybrid already has correct styling)

- [ ] **Step 5: Commit**

```bash
git add frontend/app.js
git commit -m "feat: dynamic hybrid road/label styling when overlay imagery is visible"
```

BEFORE marking this task complete:
1. Review `dev/testing-pitfalls.md` — especially Pitfall about JavaScript truthiness for numeric zero (heading=0). The paint override values include `0` nowhere, so this is not a concern here. But verify no `||` fallback is used with paint values.
2. Verify the `style.load` handler correctly clears `_savedBasemapPaint` before re-calling `_updateOverlayImageryState()` to avoid restoring stale values from the old style.

---

## Review Checkpoint

After every logical group of tasks:
Carefully review the batch of work from multiple perspectives. Do a minimum
of three review rounds; if you still find substantive issues in the third
review, keep going until there are no findings. Then update your private
journal and continue onto the next tasks.

Specifically verify:
1. **Task 1:** Does `_run_gdaladdo_with_metadata_fixup` use `run_gdal_subprocess` (not `subprocess.run`)? Does the cancel guard prevent metadata fixup on partial data?
2. **Task 2:** Does the catalog endpoint open MBTiles in read-only mode? Does it handle corrupt/busy files without crashing?
3. **Task 3:** Does the paint override table include full expression objects for `line-width`? Does `style.load` correctly clear stale snapshots?
4. **Cross-task:** No files are modified by more than one task. No import/naming conflicts.
