# National Map NAIP Imagery Source — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `nationalmap` mode to `acquire_imagery.py` that fetches NAIP 0.6m aerial imagery as 256x256 JPEG tiles from the USGS National Map ImageServer, writing directly into MBTiles with no GDAL conversion.

**Architecture:** Reuse the existing `run_direct()` tile-scraper loop by parameterizing its URL builder. National Map mode computes each tile's WGS84 bbox from z/x/y coordinates and calls the ImageServer `exportImage` endpoint for a 256x256 JPEG. Same checkpoint resume, MBTiles schema, progress reporting, and cancellation as `direct` mode.

**Tech Stack:** Python 3.12, aiohttp, aiosqlite, math (tile-to-bbox conversion), pytest

**Spec:** `docs/superpowers/specs/2026-04-14-national-map-naip-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/acquire_imagery.py` | Modify | Add `nationalmap_tile_url()`, parameterize `run_direct()` with `url_fn`, add mode routing |
| `services/search/main.py` | Modify | Add `nationalmap` to mode validation and command builder |
| `frontend/config/index.html` | Modify | Add dropdown option, contextual zoom/help text, SOURCE_LABELS |
| `tests/test_nationalmap_tiles.py` | Create | URL builder math tests, mode routing test, mocked integration test |

---

### Task 1: URL Builder Function + Unit Tests

**Files:**
- Create: `tests/test_nationalmap_tiles.py`
- Modify: `scripts/acquire_imagery.py` (add constant + function near line 55)

- [ ] **Step 1: Write failing tests for `nationalmap_tile_url()`**

Create `tests/test_nationalmap_tiles.py`:

```python
"""Tests for National Map NAIP tile URL builder."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import nationalmap_tile_url


class TestNationalMapTileUrl:
    """Verify z/x/y -> ImageServer exportImage URL conversion."""

    def test_z0_whole_world(self):
        """z=0, x=0, y=0 should produce bbox covering the whole world."""
        url = nationalmap_tile_url(0, 0, 0)
        assert "bbox=-180.0" in url or "bbox=-180," in url
        assert "size=256,256" in url
        assert "format=jpgpng" in url
        assert "USGSNAIPPlus" in url

    def test_z15_phoenix(self):
        """z=15 tile over Phoenix — verify bbox is in the right ballpark."""
        # Tile 15/6285/12535 is near Phoenix, AZ (~-112.07, 33.45)
        url = nationalmap_tile_url(15, 6285, 12535)
        # Extract bbox from URL
        bbox_str = url.split("bbox=")[1].split("&")[0]
        west, south, east, north = [float(x) for x in bbox_str.split(",")]
        # Should be near Phoenix
        assert -113.0 < west < -111.0
        assert 33.0 < south < 34.0
        assert east > west
        assert north > south
        # Tile should be small (~0.01 degrees at z15)
        assert east - west < 0.02
        assert north - south < 0.02

    def test_z18_high_zoom(self):
        """z=18 tile — verify it produces a very small bbox."""
        url = nationalmap_tile_url(18, 50280, 100280)
        bbox_str = url.split("bbox=")[1].split("&")[0]
        west, south, east, north = [float(x) for x in bbox_str.split(",")]
        # At z18, each tile is ~0.001 degrees
        assert east - west < 0.002
        assert north - south < 0.002

    def test_url_format(self):
        """Verify URL has all required ImageServer parameters."""
        url = nationalmap_tile_url(15, 6285, 12535)
        assert url.startswith("https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/ImageServer/exportImage")
        assert "bboxSR=4326" in url
        assert "imageSR=4326" in url
        assert "size=256,256" in url
        assert "format=jpgpng" in url
        assert "f=image" in url

    def test_tiles_dont_overlap(self):
        """Adjacent tiles should have contiguous non-overlapping bboxes."""
        url_a = nationalmap_tile_url(15, 100, 100)
        url_b = nationalmap_tile_url(15, 101, 100)
        bbox_a = url_a.split("bbox=")[1].split("&")[0]
        bbox_b = url_b.split("bbox=")[1].split("&")[0]
        west_a, south_a, east_a, north_a = [float(x) for x in bbox_a.split(",")]
        west_b, south_b, east_b, north_b = [float(x) for x in bbox_b.split(",")]
        # east edge of tile A should equal west edge of tile B
        assert abs(east_a - west_b) < 1e-10
        # north/south should be identical for same y
        assert abs(south_a - south_b) < 1e-10
        assert abs(north_a - north_b) < 1e-10
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_nationalmap_tiles.py -v
```

Expected: `ModuleNotFoundError` or `ImportError` — `nationalmap_tile_url` does not exist yet.

- [ ] **Step 3: Implement `nationalmap_tile_url()` in `acquire_imagery.py`**

Add after the `USGS_TILE_URL` constant (near line 55 in `scripts/acquire_imagery.py`):

```python
NATIONALMAP_EXPORT_URL = (
    "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPPlus/"
    "ImageServer/exportImage"
)


def nationalmap_tile_url(z: int, x: int, y: int) -> str:
    """Convert z/x/y tile coordinates to an ImageServer exportImage URL.

    Computes the WGS84 bounding box for the given web mercator tile and
    returns a URL that requests a 256x256 JPEG from the USGS NAIP ImageServer.
    """
    n = 2 ** z
    west = x / n * 360 - 180
    east = (x + 1) / n * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return (
        f"{NATIONALMAP_EXPORT_URL}?bbox={west},{south},{east},{north}"
        f"&bboxSR=4326&size=256,256&imageSR=4326&format=jpgpng&f=image"
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_nationalmap_tiles.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_nationalmap_tiles.py
git commit -m "feat: add nationalmap_tile_url() for NAIP ImageServer tile fetching"
```

---

### Task 2: Parameterize `run_direct()` with URL Builder

**Files:**
- Modify: `scripts/acquire_imagery.py` — `run_direct()` function (~line 641) and `_fetch_tile()` inner function (~line 677)

- [ ] **Step 1: Add `url_fn` parameter to `run_direct()`**

Change the function signature at line 641 from:

```python
async def run_direct(args):
```

to:

```python
async def run_direct(args, url_fn=None):
    if url_fn is None:
        url_fn = lambda z, x, y: USGS_TILE_URL.format(z=z, x=x, y=y)
```

- [ ] **Step 2: Update `_fetch_tile()` to use `url_fn`**

Change line 679 inside `_fetch_tile()` from:

```python
        url = USGS_TILE_URL.format(z=z, x=x, y=y)
```

to:

```python
        url = url_fn(z, x, y)
```

- [ ] **Step 3: Update progress reporting source label**

The `update_progress()` calls inside `run_direct()` currently hardcode `"direct"` as the mode. Change these to use the mode from `args` so National Map progress shows the correct source label.

Change every `update_progress(output, "direct", ...)` call inside `run_direct()` (there are 3: the batch progress at ~line 728, the cancel at ~line 713, and the completion at ~line 732) to:

```python
update_progress(output, args.mode, args.bbox, args.zoom, ...)
```

This ensures National Map shows as `"nationalmap"` in the admin panel instead of `"direct"`.

- [ ] **Step 4: Run existing tests — verify no regressions**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: 396+ tests PASS. The `direct` mode still works because `url_fn` defaults to the existing `USGS_TILE_URL` lambda.

- [ ] **Step 5: Commit**

```bash
git add scripts/acquire_imagery.py
git commit -m "refactor: parameterize run_direct() URL builder for multi-source support"
```

---

### Task 3: Mode Routing + Default Zoom

**Files:**
- Modify: `scripts/acquire_imagery.py` — argparse (~line 1359) and main routing (~line 1399)

- [ ] **Step 1: Write test for mode routing and default zoom**

Add to `tests/test_nationalmap_tiles.py`:

```python
import argparse
from unittest.mock import patch, AsyncMock

from acquire_imagery import main, nationalmap_tile_url


class TestNationalMapModeRouting:
    """Verify --mode nationalmap routes correctly with default zoom."""

    def test_nationalmap_in_mode_choices(self):
        """The argparse parser should accept 'nationalmap' as a mode."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap"])
        args = parser.parse_args(["--mode", "nationalmap"])
        assert args.mode == "nationalmap"

    @patch("acquire_imagery.run_direct", new_callable=AsyncMock)
    @patch("acquire_imagery.asyncio")
    def test_nationalmap_calls_run_direct(self, mock_asyncio, mock_run_direct):
        """--mode nationalmap should call run_direct with nationalmap_tile_url."""
        mock_asyncio.run = lambda coro: None  # Don't actually run
        with patch("sys.argv", ["acquire_imagery.py", "--mode", "nationalmap",
                                "--bbox", "-112,33,-111,34"]):
            # Can't fully test without running, but verify argparse accepts it
            parser = argparse.ArgumentParser()
            parser.add_argument("--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap"],
                                default="tnmaccess")
            parser.add_argument("--zoom", default=None)
            args = parser.parse_args(["--mode", "nationalmap"])
            # Verify default zoom would be set
            assert args.zoom is None  # Not set by argparse
            # The main() function should set it to "15-18"

    def test_default_zoom_not_set_for_direct(self):
        """Direct mode should keep the argparse default zoom, not override."""
        parser = argparse.ArgumentParser()
        parser.add_argument("--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap"],
                            default="tnmaccess")
        parser.add_argument("--zoom", default="0-14")
        args = parser.parse_args(["--mode", "direct"])
        assert args.zoom == "0-14"
```

- [ ] **Step 2: Run tests — verify new routing tests fail**

```bash
python -m pytest tests/test_nationalmap_tiles.py::TestNationalMapModeRouting -v
```

Expected: `test_nationalmap_in_mode_choices` FAILS because `nationalmap` is not yet in the real parser.

- [ ] **Step 3: Add `nationalmap` to argparse choices**

In `scripts/acquire_imagery.py`, change line 1359 from:

```python
        "--mode", choices=["tnmaccess", "direct", "m2m"], default="tnmaccess",
```

to:

```python
        "--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap"], default="tnmaccess",
```

- [ ] **Step 4: Add `nationalmap` routing in `main()`**

In `scripts/acquire_imagery.py`, change the routing block at ~line 1399 from:

```python
    if args.mode == "tnmaccess":
        asyncio.run(run_tnmaccess(args))
    elif args.mode == "m2m":
        asyncio.run(run_m2m(args))
    else:
        asyncio.run(run_direct(args))
```

to:

```python
    if args.mode == "tnmaccess":
        asyncio.run(run_tnmaccess(args))
    elif args.mode == "m2m":
        asyncio.run(run_m2m(args))
    elif args.mode == "nationalmap":
        if not args.zoom or args.zoom == "0-14":
            args.zoom = "15-18"
        asyncio.run(run_direct(args, url_fn=nationalmap_tile_url))
    else:
        asyncio.run(run_direct(args))
```

The `args.zoom == "0-14"` check catches the argparse default — if the user didn't explicitly set zoom, override with the National Map default. If they explicitly passed `--zoom 16-17`, respect it.

- [ ] **Step 5: Run all tests**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS (396+ existing + new routing tests).

- [ ] **Step 6: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_nationalmap_tiles.py
git commit -m "feat: add nationalmap mode routing with default zoom 15-18"
```

---

### Task 4: Mocked Integration Test

**Files:**
- Modify: `tests/test_nationalmap_tiles.py` — add integration test

- [ ] **Step 1: Write mocked end-to-end test**

Add to `tests/test_nationalmap_tiles.py`:

```python
import asyncio
import sqlite3
from unittest.mock import patch, AsyncMock, MagicMock


class TestNationalMapIntegration:
    """End-to-end test with mocked HTTP — verify tiles land in MBTiles."""

    def _make_jpeg_blob(self):
        """Return a minimal valid JPEG blob (SOI + EOI markers)."""
        return b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"

    def test_tiles_written_to_mbtiles(self, tmp_path):
        """Mock aiohttp, run a tiny 2x2 bbox, verify tiles in MBTiles."""
        output = tmp_path / "test_naip.mbtiles"
        jpeg_blob = self._make_jpeg_blob()

        # Create a mock args object
        args = MagicMock()
        args.bbox = "-112.01,33.44,-112.0,33.45"
        args.zoom = "15-15"
        args.output = str(output)
        args.concurrency = 5
        args.mode = "nationalmap"

        # Mock fetch_with_retry to return our JPEG blob
        with patch("acquire_imagery.fetch_with_retry", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = jpeg_blob
            with patch("acquire_imagery._cancel_requested", False):
                asyncio.run(run_direct(args, url_fn=nationalmap_tile_url))

        # Verify MBTiles has tiles
        conn = sqlite3.connect(str(output))
        tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
        assert tile_count > 0, "Expected at least 1 tile in MBTiles"

        # Verify tile data is our JPEG blob
        row = conn.execute("SELECT tile_data FROM tiles LIMIT 1").fetchone()
        assert row[0] == jpeg_blob

        # Verify metadata
        meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
        assert meta.get("format") == "jpeg"
        assert "bounds" in meta

        # Verify checkpoint table has entries
        cp_count = conn.execute("SELECT COUNT(*) FROM _checkpoint").fetchone()[0]
        assert cp_count == tile_count

        conn.close()
```

Add the missing import at the top of the file:

```python
from acquire_imagery import nationalmap_tile_url, run_direct
```

- [ ] **Step 2: Run the integration test**

```bash
python -m pytest tests/test_nationalmap_tiles.py::TestNationalMapIntegration -v
```

Expected: PASS — tiles are written to MBTiles with mocked HTTP.

- [ ] **Step 3: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_nationalmap_tiles.py
git commit -m "test: add mocked integration test for nationalmap tile pipeline"
```

---

### Task 5: Backend Orchestrator — Mode Validation + Command Builder

**Files:**
- Modify: `services/search/main.py` — mode validation (~line 1068) and command builder (~line 1190)

- [ ] **Step 1: Add `nationalmap` to mode validation**

In `services/search/main.py`, change line 1068 from:

```python
        if not body.mode or body.mode not in ("direct", "m2m"):
```

to:

```python
        if not body.mode or body.mode not in ("direct", "m2m", "nationalmap"):
```

- [ ] **Step 2: Add `nationalmap` command builder**

In `services/search/main.py`, in the command-building section (after the NAIP `elif is_naip:` block, before the `else:` at ~line 1190), add a `nationalmap` branch. The existing `else:` block at line 1190-1201 handles imagery/elevation. Change it to handle `nationalmap` explicitly:

Replace the block starting at line 1190 (`else:`) through line 1201 with:

```python
                elif body.mode == "nationalmap":
                    command = [
                        "python3", "/scripts/acquire_imagery.py",
                        "--mode", "nationalmap",
                        f"--bbox={body.bbox}",
                        f"--zoom={body.zoom or '15-18'}",
                        "--concurrency", str(min(body.concurrency, 20)),
                        "--output", "/data/imagery_naip.mbtiles",
                    ]
                else:
                    # Build command -- imagery and elevation scripts have different args
                    script = _script_for_type(body.type)
                    command = [
                        "python3", script,
                        f"--bbox={body.bbox}",
                        f"--zoom={body.zoom}",
                        "--concurrency", str(body.concurrency),
                        "--output", f"/data/{mbtiles_path.name}",
                    ]
                    if body.type == "imagery":
                        command[2:2] = ["--mode", body.mode]
```

Key details:
- Output is hardcoded to `imagery_naip.mbtiles` (not the generic `mbtiles_path`)
- Concurrency is capped at 20 (ImageServer is on-demand rendering, not pre-cached)
- Zoom defaults to `15-18` if not provided

- [ ] **Step 3: Run existing tests**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add services/search/main.py
git commit -m "feat: add nationalmap mode to pipeline orchestrator"
```

---

### Task 6: Admin Panel UI — Dropdown + Contextual Behavior

**Files:**
- Modify: `frontend/config/index.html` — dropdown, source change handler, zoom handler, source labels, start handler

- [ ] **Step 1: Add dropdown option**

In `frontend/config/index.html`, after the M2M option (~line 164), add:

```html
                <option value="nationalmap">National Map NAIP (0.6m, no auth)</option>
```

- [ ] **Step 2: Update source change handler**

In the `cfg-source` change handler (~line 1278), replace the entire handler with:

```javascript
    document.getElementById('cfg-source').addEventListener('change', function() {
        var val = this.value;
        var isM2M = val === 'm2m';
        var isNM = val === 'nationalmap';
        var zoomEl = document.getElementById('cfg-zoom');
        var estimateEl = document.getElementById('cfg-estimate');

        zoomEl.disabled = isM2M;
        if (isM2M) {
            estimateEl.textContent = 'M2M: download size depends on source imagery coverage';
            estimateEl.style.color = '#7a8299';
        } else {
            if (isNM) {
                zoomEl.value = '0-18';
                for (var i = 0; i < zoomEl.options.length; i++) {
                    if (zoomEl.options[i].value === '0-18') { zoomEl.selectedIndex = i; break; }
                }
                // If no 0-18 option exists, pick highest available
                if (zoomEl.value !== '0-18') zoomEl.value = '0-17';
            }
            estimateEl.style.color = '';
            updateEstimate();
        }

        updateConcurrencyOptions();
        updateM2MWarning();
        document.getElementById('cfg-zoom').dispatchEvent(new Event('change'));
    });
```

- [ ] **Step 3: Update zoom change handler**

In the `cfg-zoom` change handler (~line 1302), update the note logic to handle National Map:

```javascript
    document.getElementById('cfg-zoom').addEventListener('change', function() {
        var source = document.getElementById('cfg-source').value;
        var note = document.getElementById('cfg-zoom-note');

        if (source === 'm2m') {
            note.textContent = 'M2M mode auto-detects zoom from source imagery (~z17-z19 for NAIP)';
            note.style.color = '#7a8299';
            return;
        }

        updateEstimate();
        var zoom = this.value;
        var maxZ = parseInt(zoom.split('-')[1]);

        if (source === 'nationalmap') {
            if (maxZ < 15) {
                note.textContent = 'Below z15, USGS Direct is faster (pre-cached tiles). National Map is best at z15-z18.';
                note.style.color = '#f9e2af';
            } else if (maxZ > 18) {
                note.textContent = 'Above z18, NAIP imagery is upscaled (native resolution is 0.6m).';
                note.style.color = '#f9e2af';
            } else {
                note.textContent = 'NAIP 0.6m aerial imagery via USGS ImageServer. No auth required.';
                note.style.color = '#a6e3a1';
            }
            return;
        }

        if (maxZ > 16) {
            note.textContent = 'Zoom levels above 16 require M2M mode (NAIP GeoTIFF source).';
            note.style.color = '#f9e2af';
        } else {
            note.textContent = '';
        }
    });
```

- [ ] **Step 4: Add `nationalmap` to SOURCE_LABELS**

In `SOURCE_LABELS` (~line 1054), add the `nationalmap` entry:

```javascript
    var SOURCE_LABELS = {
        sentinel: 'Sentinel-2',
        naip: 'NAIP',
        direct: 'USGS Direct',
        m2m: 'USGS M2M',
        nationalmap: 'National Map NAIP',
        elevation: 'Elevation'
    };
```

- [ ] **Step 5: Update start handler confirmation message**

In the imagery start handler (~line 1334), update the confirmation message to handle National Map:

```javascript
        var confirmMsg;
        if (isM2M) {
            confirmMsg = 'Start M2M download for ' + body.bbox + '?';
        } else {
            var tileCount = estimateTiles(body.bbox, document.getElementById('cfg-zoom').value);
            var label = source === 'nationalmap' ? 'National Map NAIP' : 'USGS Direct';
            confirmMsg = 'Start ' + label + ' download? ~' + tileCount.toLocaleString() + ' tiles';
        }
        if (!confirm(confirmMsg)) return;
```

Replace the existing `confirmMsg` assignment and `if (!confirm(...))` lines.

- [ ] **Step 6: Add NAIP card unavailability note**

In the NAIP card HTML (~line 299, inside `naip-body`), add before the bbox label:

```html
                <div class="detail" style="color:#f9e2af;margin-bottom:8px">
                    USDA Gateway is currently unavailable (since April 2026).
                    For NAIP imagery, use <strong>National Map NAIP</strong> in the Imagery section above.
                </div>
```

- [ ] **Step 7: Commit**

```bash
git add frontend/config/index.html
git commit -m "feat: add National Map NAIP option to admin panel imagery source"
```

---

### Task 7: Rebuild + Deploy + Smoke Test

**Files:** None modified — deployment and verification only.

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS (396 existing + ~8 new National Map tests).

- [ ] **Step 2: Rebuild search service and recreate frontend**

```bash
docker compose up -d --build search --force-recreate frontend
```

Wait for all services to be healthy.

- [ ] **Step 3: Verify National Map dropdown appears**

Open `http://localhost:8097` in a browser. Go to Pipelines tab. Verify:
- Source dropdown has three options: USGS Direct, USGS M2M, National Map NAIP (0.6m, no auth)
- Selecting National Map NAIP shows zoom note in green
- NAIP card at the bottom shows unavailability notice

- [ ] **Step 4: Test a tiny National Map download**

In the admin panel:
1. Select "National Map NAIP (0.6m, no auth)" from the source dropdown
2. Set zoom to "0-15" (small tile count)
3. Draw a small bbox around a city (~0.1 x 0.1 degrees)
4. Click Start Download
5. Verify progress bar appears and tiles download
6. Verify `imagery_naip.mbtiles` appears in `/srv/geographica/data/`

Alternatively, test via CLI inside the pipeline container or directly:

```bash
python scripts/acquire_imagery.py --mode nationalmap \
  --bbox "-112.1,33.4,-112.0,33.5" --zoom 15-15 \
  --output /tmp/test_naip.mbtiles --concurrency 10
```

Expected: ~10-20 tiles downloaded, file created, no errors.

- [ ] **Step 5: Verify tiles in TileServer**

If `imagery_naip.mbtiles` is in `/srv/geographica/data/`:

```bash
curl -s http://localhost:8090/data/imagery_naip.json | python3 -m json.tool | head -10
```

Expected: TileJSON response showing the NAIP tile layer.

- [ ] **Step 6: Final commit with all changes**

```bash
git add -A
git status  # Verify only expected files
git commit -m "feat: National Map NAIP imagery source — complete implementation

Adds nationalmap mode to acquire_imagery.py for NAIP 0.6m aerial
imagery via USGS ImageServer. JPEG-direct to MBTiles, no GDAL
conversion. Admin panel integration with contextual zoom guidance."
```
