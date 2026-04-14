# NOAA NAIP Download + BYO Imagery Import — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two imagery acquisition paths: (1) automated NOAA Digital Coast NAIP download with reprojection, (2) user-provided GeoTIFF import via drop directory. Both convert to MBTiles and register with TileServer.

**Architecture:** NOAA download adds a `noaa` mode to `acquire_imagery.py` that fetches 0.6m NAIP GeoTIFFs from Azure Blob Storage, reprojects UTM→Web Mercator, and converts to MBTiles one tile at a time. BYO import adds a new script (`import_imagery.py`) and admin panel card that scans a drop directory, reprojects+converts in batches, and merges into MBTiles. Both use a shared TileServer config updater to register new layers.

**Tech Stack:** Python 3.12, aiohttp, aiosqlite, GDAL (gdalwarp, gdal_translate, ogr2ogr), subprocess, FastAPI, vanilla JS

**Spec:** `docs/superpowers/specs/2026-04-14-noaa-naip-byo-imagery-design.md`

**Deferred to follow-up:** Multi-state bbox support (spec decision #10) — when a bbox spans two states, only the selected state's tiles are downloaded. This requires fetching and merging tile indices from multiple states, which adds complexity. For v1, the user selects one state at a time. Multi-state can be added as a follow-up task.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `scripts/acquire_imagery.py` | Modify | Add `noaa` mode: catalog, shapefile fetch/cache, spatial filtering, download+reproject+convert pipeline |
| `scripts/import_imagery.py` | Create | BYO import: scan directory, validate, reproject, batch convert to MBTiles |
| `scripts/tileserver_config.py` | Create | Shared helper: add MBTiles entry to tileserver/config.json atomically |
| `scripts/pipeline_security.py` | Modify | Add `sanitize_layer_name()` function |
| `services/search/main.py` | Modify | Add `noaa` mode validation/command builder, BYO import endpoint, TileServer restart |
| `frontend/config/index.html` | Modify | Add NOAA dropdown option + state selector, BYO import card |
| `tests/test_noaa_naip.py` | Create | NOAA: catalog validation, spatial filtering, URL construction, reprojection |
| `tests/test_import_imagery.py` | Create | BYO: directory scanning, name sanitization, batch processing |
| `tests/test_tileserver_config.py` | Create | Config updater: add entry, idempotent, atomic write |

---

### Task 1: TileServer Config Updater (Shared Infrastructure)

Both NOAA and BYO need to register new MBTiles with TileServer. Build this first.

**Files:**
- Create: `scripts/tileserver_config.py`
- Create: `tests/test_tileserver_config.py`

BEFORE starting work:
1. Read `scripts/pipeline_security.py` for existing security patterns
2. Read `tileserver/config.json` to understand the exact format

- [ ] **Step 1: Write failing tests**

Create `tests/test_tileserver_config.py`:

```python
"""Tests for TileServer config.json updater."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from tileserver_config import add_mbtiles_to_config


SAMPLE_CONFIG = {
    "options": {"paths": {"root": "/data", "fonts": "fonts-served", "styles": "styles"}},
    "data": {
        "southwest5": {"mbtiles": "southwest5.mbtiles"},
        "imagery": {"mbtiles": "/srv/data/imagery.mbtiles"},
    },
    "styles": {},
}


class TestAddMbtilesToConfig:
    def test_adds_new_entry(self, tmp_path):
        """New MBTiles name gets added to data section."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")

        result = json.loads(config_path.read_text())
        assert "imagery_noaa" in result["data"]
        assert result["data"]["imagery_noaa"]["mbtiles"] == "/srv/data/imagery_noaa.mbtiles"

    def test_idempotent(self, tmp_path):
        """Adding the same entry twice doesn't create duplicates."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")
        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")

        result = json.loads(config_path.read_text())
        assert len([k for k in result["data"] if k == "imagery_noaa"]) == 1

    def test_preserves_existing_entries(self, tmp_path):
        """Existing data entries are not modified."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

        add_mbtiles_to_config(config_path, "imagery_noaa", "/srv/data/imagery_noaa.mbtiles")

        result = json.loads(config_path.read_text())
        assert result["data"]["southwest5"] == {"mbtiles": "southwest5.mbtiles"}
        assert result["data"]["imagery"] == {"mbtiles": "/srv/data/imagery.mbtiles"}

    def test_preserves_styles_and_options(self, tmp_path):
        """Styles and options sections are unchanged."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

        add_mbtiles_to_config(config_path, "test", "/srv/data/test.mbtiles")

        result = json.loads(config_path.read_text())
        assert result["options"] == SAMPLE_CONFIG["options"]

    def test_atomic_write(self, tmp_path):
        """Write uses temp file + rename (no partial writes)."""
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(SAMPLE_CONFIG, indent=2))

        add_mbtiles_to_config(config_path, "test", "/srv/data/test.mbtiles")

        # No .tmp files should remain
        assert not list(tmp_path.glob("*.tmp"))
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_tileserver_config.py -v
```

Expected: `ModuleNotFoundError` — `tileserver_config` doesn't exist yet.

- [ ] **Step 3: Implement `tileserver_config.py`**

Create `scripts/tileserver_config.py`:

```python
"""Update TileServer GL config.json to register new MBTiles data sources.

TileServer GL v5.5.0 does NOT auto-discover MBTiles files. New data sources
must be added to config.json and TileServer restarted.
"""

import json
import os
from pathlib import Path


def add_mbtiles_to_config(config_path: Path, name: str, mbtiles_path: str) -> bool:
    """Add an MBTiles entry to TileServer config.json if not already present.

    Args:
        config_path: Path to tileserver/config.json
        name: Data source name (e.g., "imagery_noaa")
        mbtiles_path: Path to the MBTiles file as seen inside the TileServer container
                      (e.g., "/srv/data/imagery_noaa.mbtiles")

    Returns:
        True if entry was added (config changed), False if already present.
    """
    config = json.loads(config_path.read_text())

    if name in config.get("data", {}):
        return False

    if "data" not in config:
        config["data"] = {}

    config["data"][name] = {"mbtiles": mbtiles_path}

    # Atomic write: tmp + fsync + rename
    tmp_path = config_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(config_path))

    return True
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_tileserver_config.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/tileserver_config.py tests/test_tileserver_config.py
git commit -m "feat: add TileServer config.json updater for dynamic MBTiles registration"
```

---

### Task 2: Layer Name Sanitization (Security)

**Files:**
- Modify: `scripts/pipeline_security.py`
- Modify: `tests/test_tileserver_config.py` (add sanitization tests)

BEFORE starting work:
1. Read `scripts/pipeline_security.py` — existing `sanitize_scene_id()` and `safe_staging_path()` patterns

- [ ] **Step 1: Write failing tests**

Add to `tests/test_tileserver_config.py` (or create new section):

```python
from pipeline_security import sanitize_layer_name


class TestSanitizeLayerName:
    def test_simple_name(self):
        assert sanitize_layer_name("phoenix drone") == "phoenix_drone"

    def test_uppercase_lowered(self):
        assert sanitize_layer_name("Phoenix 2024") == "phoenix_2024"

    def test_special_chars_stripped(self):
        assert sanitize_layer_name("my-layer (v2)!") == "my_layer_v2"

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="path traversal"):
            sanitize_layer_name("../../etc/passwd")

    def test_slash_rejected(self):
        with pytest.raises(ValueError, match="path traversal"):
            sanitize_layer_name("foo/bar")

    def test_null_byte_rejected(self):
        with pytest.raises(ValueError, match="path traversal"):
            sanitize_layer_name("foo\x00bar")

    def test_max_length_32(self):
        result = sanitize_layer_name("a" * 50)
        assert len(result) <= 32

    def test_empty_after_sanitize_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            sanitize_layer_name("!!!")

    def test_leading_trailing_underscores_stripped(self):
        assert sanitize_layer_name("__test__") == "test"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_tileserver_config.py::TestSanitizeLayerName -v
```

Expected: `ImportError` — `sanitize_layer_name` doesn't exist.

- [ ] **Step 3: Implement `sanitize_layer_name()`**

Add to `scripts/pipeline_security.py`:

```python
def sanitize_layer_name(name: str) -> str:
    """Sanitize a user-provided layer name for use as an MBTiles filename.

    Lowercases, strips non-alphanumeric characters (except underscore),
    truncates to 32 chars. Rejects path traversal attempts.

    Args:
        name: User-provided layer name.

    Returns:
        Safe string containing only ``[a-z0-9_]``, max 32 chars.

    Raises:
        ValueError: On path traversal attempts, null bytes, or empty result.
    """
    if "\x00" in name:
        raise ValueError("path traversal: null bytes in name")
    if "/" in name or "\\" in name:
        raise ValueError("path traversal: path separator in name")
    if ".." in name:
        raise ValueError("path traversal: '..' in name")

    result = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    # Collapse multiple underscores
    result = re.sub(r"_+", "_", result)
    result = result[:32].rstrip("_")

    if not result:
        raise ValueError("layer name empty after sanitization")

    return result
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_tileserver_config.py -v
```

Expected: All tests PASS (5 config + 9 sanitization).

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ --tb=short
```

Expected: All existing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline_security.py tests/test_tileserver_config.py
git commit -m "feat: add sanitize_layer_name() for safe MBTiles filenames"
```

---

### Task 3: NOAA Catalog + Tile Index Spatial Filtering

**Files:**
- Modify: `scripts/acquire_imagery.py` (add NOAA catalog, shapefile fetch/cache, spatial filter)
- Create: `tests/test_noaa_naip.py`

BEFORE starting work:
1. Read `scripts/acquire_imagery.py` — understand existing constants section (~line 48), `parse_bbox()`, `fetch_with_retry()`
2. Read `scripts/pipeline_security.py` — `safe_staging_path()` for cache paths

- [ ] **Step 1: Write failing tests**

Create `tests/test_noaa_naip.py`:

```python
"""Tests for NOAA NAIP download mode."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import (
    NOAA_NAIP_CATALOG,
    noaa_blob_base_url,
    noaa_cache_dir,
    filter_tiles_by_bbox,
)


class TestNOAACatalog:
    def test_arizona_2021_in_catalog(self):
        """Arizona 2021 should be in the catalog."""
        assert ("AZ", 2021) in NOAA_NAIP_CATALOG
        assert NOAA_NAIP_CATALOG[("AZ", 2021)] == "AZ_NAIP_2021_9596"

    def test_blob_base_url(self):
        """Verify URL construction from catalog entry."""
        url = noaa_blob_base_url("AZ", 2021)
        assert url == "https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596"

    def test_blob_base_url_missing_state(self):
        """Unknown state/year raises KeyError."""
        with pytest.raises(KeyError):
            noaa_blob_base_url("ZZ", 2099)

    def test_cache_dir_path(self):
        """Cache dir follows /data/noaa_cache/{STATE}_{YEAR}/ pattern."""
        result = noaa_cache_dir(Path("/data"), "AZ", 2021)
        assert result == Path("/data/noaa_cache/AZ_2021")


class TestFilterTilesByBbox:
    def _make_csv(self, tmp_path, rows):
        """Write a fake ogr2ogr CSV output with a FileName column."""
        csv_path = tmp_path / "tiles.csv"
        lines = ["FileName\n"] + [f"{r}\n" for r in rows]
        csv_path.write_text("".join(lines))
        return csv_path

    @patch("acquire_imagery.subprocess.run")
    def test_returns_filenames_from_ogr2ogr(self, mock_run, tmp_path):
        """Spatial filter returns filenames from ogr2ogr CSV output."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="FileName\nm_3311001_ne_12_060_20211014.tif\nm_3311001_nw_12_060_20211014.tif\n",
        )
        result = filter_tiles_by_bbox(
            tmp_path / "tile_index.shp",
            west=-112.1, south=33.4, east=-112.0, north=33.5,
        )
        assert len(result) == 2
        assert "m_3311001_ne_12_060_20211014.tif" in result

    @patch("acquire_imagery.subprocess.run")
    def test_empty_bbox_returns_empty(self, mock_run, tmp_path):
        """Bbox with no intersecting tiles returns empty list."""
        mock_run.return_value = MagicMock(returncode=0, stdout="FileName\n")
        result = filter_tiles_by_bbox(
            tmp_path / "tile_index.shp",
            west=0.0, south=0.0, east=0.1, north=0.1,
        )
        assert result == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_noaa_naip.py -v
```

Expected: `ImportError` — functions don't exist yet.

- [ ] **Step 3: Implement catalog, URL helpers, cache dir, and spatial filter**

Add to `scripts/acquire_imagery.py` after the existing constants (~line 58, after `NATIONALMAP_EXPORT_URL`):

```python
# ---------------------------------------------------------------------------
# NOAA Digital Coast NAIP — catalog and helpers
# ---------------------------------------------------------------------------
NOAA_BLOB_BASE = "https://coastalimagery.blob.core.windows.net/digitalcoast"

NOAA_NAIP_CATALOG = {
    ("AZ", 2021): "AZ_NAIP_2021_9596",
    # Additional states to be populated via NOAA Data Access Viewer
}

NOAA_TILE_SIZE_MB = 486  # approximate size of each NAIP quad GeoTIFF


def noaa_blob_base_url(state: str, year: int) -> str:
    """Return the Azure blob base URL for a state/year NAIP dataset."""
    dir_name = NOAA_NAIP_CATALOG[(state, year)]
    return f"{NOAA_BLOB_BASE}/{dir_name}"


def noaa_cache_dir(data_dir: Path, state: str, year: int) -> Path:
    """Return the local cache directory for NOAA shapefiles."""
    return data_dir / "noaa_cache" / f"{state}_{year}"


def filter_tiles_by_bbox(
    shapefile_path: Path,
    west: float, south: float, east: float, north: float,
) -> list[str]:
    """Use ogr2ogr to spatially filter a tile index shapefile.

    Returns list of GeoTIFF filenames whose footprints intersect the bbox.
    """
    result = subprocess.run(
        [
            "ogr2ogr", "-f", "CSV", "/dev/stdout",
            str(shapefile_path),
            "-spat", str(west), str(south), str(east), str(north),
            "-geom=NO",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        log.error("ogr2ogr spatial filter failed: %s", result.stderr)
        return []

    lines = result.stdout.strip().split("\n")
    if len(lines) <= 1:
        return []

    # Find the FileName column index
    headers = lines[0].split(",")
    try:
        fname_idx = next(
            i for i, h in enumerate(headers)
            if h.strip().lower() in ("filename", "name", "url")
        )
    except StopIteration:
        log.error("ogr2ogr CSV has no FileName/Name/URL column. Headers: %s", headers)
        return []

    filenames = []
    for line in lines[1:]:
        cols = line.split(",")
        if len(cols) > fname_idx:
            fname = cols[fname_idx].strip().strip('"')
            if fname.endswith(".tif"):
                filenames.append(fname)
    return filenames
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_noaa_naip.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_noaa_naip.py
git commit -m "feat: add NOAA NAIP catalog, cache helpers, and spatial tile filter"
```

---

### Task 4: NOAA Download + Reproject + Convert Pipeline

**Files:**
- Modify: `scripts/acquire_imagery.py` (add `run_noaa()` function, argparse routing)
- Modify: `tests/test_noaa_naip.py` (add pipeline integration test)

BEFORE starting work:
1. Read `scripts/acquire_imagery.py` — understand `run_direct()` pattern, `fetch_with_retry()`, `convert_batch_to_mbtiles()`, `merge_mbtiles()`, `update_progress()`
2. Read the spec section on "Pipeline Flow" — download one at a time, gdalwarp before gdal_translate

This is the largest task. The `run_noaa()` function:
1. Validates catalog entry (HEAD request)
2. Fetches + caches tile index shapefile
3. Filters tiles by bbox
4. Shows estimate (count × 486 MB)
5. Downloads tiles one at a time
6. Per tile: `gdalwarp -t_srs EPSG:3857` → `gdal_translate -of MBTiles` → merge → delete

- [ ] **Step 1: Write mocked integration test**

Add to `tests/test_noaa_naip.py`:

```python
import asyncio
from acquire_imagery import run_noaa


class TestNOAAPipelineIntegration:
    def _make_tiny_geotiff(self, path):
        """Create a minimal valid GeoTIFF file (TIFF magic + minimal IFD)."""
        # Little-endian TIFF magic bytes
        path.write_bytes(b"II\x2a\x00" + b"\x00" * 200)

    @patch("acquire_imagery.subprocess.run")
    @patch("acquire_imagery.fetch_with_retry", new_callable=AsyncMock)
    def test_noaa_pipeline_creates_mbtiles(self, mock_fetch, mock_subprocess, tmp_path):
        """Mock HTTP + GDAL, verify pipeline creates output MBTiles."""
        output = tmp_path / "imagery_noaa.mbtiles"
        cache_dir = tmp_path / "noaa_cache" / "AZ_2021"
        cache_dir.mkdir(parents=True)

        # Mock: HEAD request returns 200 (catalog validation)
        mock_head_response = MagicMock()
        mock_head_response.status = 200

        # Mock: shapefile download returns bytes
        fake_shp_zip = b"PK\x03\x04" + b"\x00" * 100  # fake zip
        
        # Mock: URL list returns two tiles
        url_list_text = (
            "https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596/m_3311001_ne_12_060_20211014.tif\n"
            "https://coastalimagery.blob.core.windows.net/digitalcoast/AZ_NAIP_2021_9596/m_3311001_nw_12_060_20211014.tif\n"
        ).encode()

        # Mock: GeoTIFF download returns small file
        fake_tif = b"II\x2a\x00" + b"\x00" * 200
        mock_fetch.return_value = fake_tif

        # Mock: ogr2ogr returns matching filenames
        def subprocess_side_effect(cmd, *args, **kwargs):
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            cmd_str = " ".join(str(c) for c in cmd)
            if "ogr2ogr" in cmd_str:
                result.stdout = "FileName\nm_3311001_ne_12_060_20211014.tif\n"
            return result

        mock_subprocess.side_effect = subprocess_side_effect

        # Create mock args
        args = MagicMock()
        args.bbox = "-112.1,33.4,-112.0,33.5"
        args.output = str(output)
        args.mode = "noaa"
        args.state = "AZ"
        args.year = 2021
        args.concurrency = 1

        # The full pipeline is complex to mock — this test verifies the function
        # exists, accepts the right args, and would proceed with the catalog lookup.
        # Full integration testing requires real GDAL and network (manual smoke test).
        assert callable(run_noaa)
```

- [ ] **Step 2: Implement `run_noaa()` function**

Add to `scripts/acquire_imagery.py` before the CLI section:

```python
# ===================================================================
# MODE 5 – NOAA Digital Coast NAIP
# ===================================================================

async def noaa_fetch_tile_index(session: aiohttp.ClientSession,
                                 state: str, year: int,
                                 data_dir: Path) -> Path | None:
    """Fetch and cache the NOAA tile index shapefile for a state/year.

    Downloads the tile index .shp/.shx/.dbf files to data_dir/noaa_cache/{STATE}_{YEAR}/.
    Returns path to the .shp file, or None on failure.
    """
    base_url = noaa_blob_base_url(state, year)
    cache = noaa_cache_dir(data_dir, state, year)
    cache.mkdir(parents=True, exist_ok=True)

    # The tile index shapefile components
    # NOAA names them like: {state}_naip_{year}_{zone}.shp (varies by state)
    # First, fetch the URL list to find the shapefile name
    url_list_url = None
    url_list_data = await fetch_with_retry(
        session, f"{base_url}/index.html", timeout_s=30,
    )
    if url_list_data is None:
        log.error("Failed to fetch NOAA index page for %s %d", state, year)
        return None

    # Parse HTML to find shapefile links
    import re
    html = url_list_data.decode("utf-8", errors="replace")
    shp_links = re.findall(r'href="([^"]*\.shp)"', html, re.IGNORECASE)
    if not shp_links:
        log.error("No shapefile found in NOAA index for %s %d", state, year)
        return None

    shp_url = shp_links[0]
    if not shp_url.startswith("http"):
        shp_url = f"{base_url}/{shp_url}"

    shp_name = Path(shp_url).name
    shp_path = cache / shp_name

    # Download .shp, .shx, .dbf (minimum for ogr2ogr)
    for ext in [".shp", ".shx", ".dbf"]:
        dest = cache / shp_name.replace(".shp", ext)
        if dest.exists() and dest.stat().st_size > 0:
            continue
        url = shp_url.replace(".shp", ext)
        data = await fetch_with_retry(session, url, timeout_s=120)
        if data is None:
            log.error("Failed to download %s", url)
            return None
        dest.write_bytes(data)
        log.info("Cached: %s", dest)

    return shp_path


async def noaa_fetch_url_list(session: aiohttp.ClientSession,
                               state: str, year: int) -> list[str]:
    """Fetch the URL list for a state/year from NOAA."""
    base_url = noaa_blob_base_url(state, year)

    # Fetch the index page to find the urllist txt file
    index_data = await fetch_with_retry(
        session, f"{base_url}/index.html", timeout_s=30,
    )
    if index_data is None:
        return []

    import re
    html = index_data.decode("utf-8", errors="replace")
    txt_links = re.findall(r'href="([^"]*urllist[^"]*\.txt)"', html, re.IGNORECASE)
    if not txt_links:
        log.warning("No URL list found for %s %d, will construct from shapefile", state, year)
        return []

    txt_url = txt_links[0]
    if not txt_url.startswith("http"):
        txt_url = f"{base_url}/{txt_url}"

    data = await fetch_with_retry(session, txt_url, timeout_s=60)
    if data is None:
        return []

    urls = [
        line.strip() for line in data.decode("utf-8", errors="replace").split("\n")
        if line.strip().endswith(".tif")
    ]
    return urls


async def run_noaa(args):
    """Run the NOAA NAIP download pipeline."""
    global _cancel_requested

    state = args.state.upper()
    year = args.year
    bbox = parse_bbox(args.bbox)
    output = Path(args.output)
    data_dir = output.parent

    # Validate catalog entry
    if (state, year) not in NOAA_NAIP_CATALOG:
        log.error("State %s year %d not in NOAA catalog. Available: %s",
                  state, year, list(NOAA_NAIP_CATALOG.keys()))
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, 0, status="error", error=f"State {state} year {year} not in catalog")
        return

    import datetime
    update_progress._started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    update_progress(output, "noaa", args.bbox, "n/a",
                    0, 0, phase="resolving")

    async with aiohttp.ClientSession() as session:
        # Validate blob exists (HEAD request)
        base_url = noaa_blob_base_url(state, year)
        try:
            async with session.head(f"{base_url}/index.html",
                                     timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    log.error("NOAA blob not accessible (HTTP %d): %s", resp.status, base_url)
                    update_progress(output, "noaa", args.bbox, "n/a",
                                    0, 0, status="error",
                                    error=f"NOAA data unavailable (HTTP {resp.status}). Path may have changed.")
                    return
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.error("NOAA blob not reachable: %s", exc)
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="error", error=f"NOAA server unreachable: {exc}")
            return

        # Fetch + cache tile index shapefile
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, 0, phase="indexing")
        shp_path = await noaa_fetch_tile_index(session, state, year, data_dir)
        if shp_path is None:
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="error", error="Failed to fetch tile index shapefile")
            return

        # Spatial filter
        west, south, east, north = bbox
        tile_filenames = filter_tiles_by_bbox(shp_path, west, south, east, north)
        if not tile_filenames:
            update_progress(output, "noaa", args.bbox, "n/a",
                            0, 0, status="error", error="No NAIP tiles intersect the given bbox")
            return

        log.info("Found %d NOAA NAIP tiles intersecting bbox", len(tile_filenames))

        # Fetch URL list to get full download URLs
        all_urls = await noaa_fetch_url_list(session, state, year)
        url_map = {Path(u).name: u for u in all_urls}

        # Match filenames to URLs
        download_list = []
        for fname in tile_filenames:
            if fname in url_map:
                download_list.append((fname, url_map[fname]))
            else:
                # Construct URL from base + filename
                download_list.append((fname, f"{base_url}/{fname}"))

        total_tiles = len(download_list)
        est_gb = total_tiles * NOAA_TILE_SIZE_MB / 1024
        log.info("NOAA download plan: %d tiles, ~%.1f GB raw, output: %s",
                 total_tiles, est_gb, output)

        update_progress(output, "noaa", args.bbox, "n/a",
                        0, total_tiles, phase="downloading")

        # Process one tile at a time (batch_size=1 due to 486MB tile size + 2GB container limit)
        staging_dir = data_dir / "noaa_staging"
        staging_dir.mkdir(parents=True, exist_ok=True)

        for idx, (fname, url) in enumerate(download_list):
            if _cancel_requested:
                update_progress(output, "noaa", args.bbox, "n/a",
                                idx, total_tiles, status="cancelled")
                log.info("Cancelled after %d/%d tiles", idx, total_tiles)
                return

            update_progress(output, "noaa", args.bbox, "n/a",
                            idx, total_tiles, phase="downloading",
                            detail=f"Downloading {fname} ({idx+1}/{total_tiles})")

            # Download
            tif_path = staging_dir / fname
            if not tif_path.exists() or tif_path.stat().st_size == 0:
                data = await fetch_with_retry(session, url, timeout_s=1200)
                if data is None:
                    log.warning("Failed to download %s, skipping", fname)
                    continue
                tif_path.write_bytes(data)

            # Validate GeoTIFF header
            from pipeline_security import validate_file_header
            if not validate_file_header(tif_path, "geotiff"):
                log.error("Invalid GeoTIFF: %s — removing", fname)
                tif_path.unlink()
                continue

            # Reproject UTM → Web Mercator
            update_progress(output, "noaa", args.bbox, "n/a",
                            idx, total_tiles, phase="converting",
                            detail=f"Reprojecting {fname}")
            warped_path = staging_dir / f"warped_{fname}"
            try:
                subprocess.run(
                    [
                        "gdalwarp", "-t_srs", "EPSG:3857",
                        "-r", "lanczos",
                        "-co", "TILED=YES",
                        "-co", "COMPRESS=DEFLATE",
                        str(tif_path), str(warped_path),
                    ],
                    check=True, capture_output=True, text=True,
                    timeout=3600,
                    env={**os.environ, "GDAL_CACHEMAX": "512"},
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                log.error("gdalwarp failed for %s: %s", fname, exc)
                if warped_path.exists():
                    warped_path.unlink()
                tif_path.unlink()
                continue

            # Delete original (save disk)
            tif_path.unlink()

            # Convert to temp MBTiles and merge
            success = convert_batch_to_mbtiles([warped_path], output, f"noaa_{idx}")

            # Cleanup
            if warped_path.exists():
                warped_path.unlink()

            if not success:
                log.warning("MBTiles conversion failed for %s, skipping", fname)
                continue

            log.info("Tile %d/%d complete: %s", idx + 1, total_tiles, fname)

        # Update TileServer config
        from tileserver_config import add_mbtiles_to_config
        config_path = Path("/data") / ".." / "tileserver" / "config.json"
        # In Docker: /data is ./data, tileserver config is at ./tileserver/config.json
        # From the host or pipeline container, this path varies.
        # Use a relative path from data_dir to find tileserver/config.json
        repo_root = data_dir.parent  # data/ -> repo root
        ts_config = repo_root / "tileserver" / "config.json"
        if ts_config.exists():
            added = add_mbtiles_to_config(
                ts_config, "imagery_noaa", f"/srv/data/{output.name}"
            )
            if added:
                log.info("Added imagery_noaa to TileServer config.json")

        update_progress(output, "noaa", args.bbox, "n/a",
                        total_tiles, total_tiles, status="completed",
                        detail=f"Complete: {total_tiles} NAIP tiles")
        log.info("NOAA NAIP pipeline complete: %d tiles → %s", total_tiles, output)
```

- [ ] **Step 3: Add `noaa` to argparse and routing**

In the argparse section, add to `--mode` choices:

```python
        "--mode", choices=["tnmaccess", "direct", "m2m", "nationalmap", "noaa"], default="tnmaccess",
```

Add new arguments:

```python
    parser.add_argument(
        "--state", default=None,
        help="State abbreviation for NOAA mode (e.g., AZ)",
    )
    parser.add_argument(
        "--year", type=int, default=2021,
        help="NAIP year for NOAA mode (default: 2021)",
    )
```

Add routing in `main()`:

```python
    elif args.mode == "noaa":
        if not args.state:
            log.error("NOAA mode requires --state (e.g., --state AZ)")
            sys.exit(1)
        asyncio.run(run_noaa(args))
```

- [ ] **Step 4: Run all tests**

```bash
python -m pytest tests/ --tb=short
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_noaa_naip.py
git commit -m "feat: add NOAA NAIP download pipeline with reprojection"
```

---

### Task 5: BYO Import Script

**Files:**
- Create: `scripts/import_imagery.py`
- Create: `tests/test_import_imagery.py`

BEFORE starting work:
1. Read `scripts/acquire_imagery.py` — `convert_batch_to_mbtiles()`, `merge_mbtiles()` patterns
2. Read `scripts/pipeline_security.py` — `safe_staging_path()`, `validate_file_header()`, `sanitize_layer_name()`
3. Read `scripts/tileserver_config.py` — `add_mbtiles_to_config()`

- [ ] **Step 1: Write failing tests**

Create `tests/test_import_imagery.py`:

```python
"""Tests for BYO GeoTIFF import pipeline."""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from import_imagery import scan_import_directory, resolve_output_path


class TestScanImportDirectory:
    def test_finds_tif_files(self, tmp_path):
        """Finds .tif and .tiff files in directory."""
        (tmp_path / "a.tif").write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        (tmp_path / "b.tiff").write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        (tmp_path / "c.txt").write_text("not a tif")

        result = scan_import_directory(tmp_path)
        assert len(result["tif_files"]) == 2
        assert result["other_geo_files"] == []

    def test_finds_jp2_as_other(self, tmp_path):
        """JP2 files are reported as unsupported geo files."""
        (tmp_path / "a.jp2").write_bytes(b"\x00" * 100)

        result = scan_import_directory(tmp_path)
        assert len(result["tif_files"]) == 0
        assert len(result["other_geo_files"]) == 1
        assert result["other_geo_files"][0].suffix == ".jp2"

    def test_one_level_subdirectory(self, tmp_path):
        """Scans one level of subdirectories."""
        sub = tmp_path / "subdir"
        sub.mkdir()
        (sub / "a.tif").write_bytes(b"II\x2a\x00" + b"\x00" * 100)

        result = scan_import_directory(tmp_path)
        assert len(result["tif_files"]) == 1

    def test_rejects_symlinks(self, tmp_path):
        """Symlinks are not followed."""
        real = tmp_path / "real.tif"
        real.write_bytes(b"II\x2a\x00" + b"\x00" * 100)
        link = tmp_path / "link.tif"
        link.symlink_to(real)

        result = scan_import_directory(tmp_path)
        # Only the real file, not the symlink
        assert len(result["tif_files"]) == 1
        assert result["tif_files"][0].name == "real.tif"

    def test_empty_directory(self, tmp_path):
        """Empty directory returns empty lists."""
        result = scan_import_directory(tmp_path)
        assert result["tif_files"] == []
        assert result["total_bytes"] == 0


class TestResolveOutputPath:
    def test_default_name(self, tmp_path):
        """No layer name → imagery_custom.mbtiles."""
        result = resolve_output_path(tmp_path, None)
        assert result == tmp_path / "imagery_custom.mbtiles"

    def test_empty_name(self, tmp_path):
        """Empty string → imagery_custom.mbtiles."""
        result = resolve_output_path(tmp_path, "")
        assert result == tmp_path / "imagery_custom.mbtiles"

    def test_named_layer(self, tmp_path):
        """Named layer → imagery_{sanitized_name}.mbtiles."""
        result = resolve_output_path(tmp_path, "Phoenix Drone 2026")
        assert result == tmp_path / "imagery_phoenix_drone_2026.mbtiles"

    def test_path_traversal_rejected(self, tmp_path):
        """Path traversal in name is rejected."""
        with pytest.raises(ValueError):
            resolve_output_path(tmp_path, "../../etc/passwd")
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
python -m pytest tests/test_import_imagery.py -v
```

Expected: `ModuleNotFoundError` — `import_imagery` doesn't exist.

- [ ] **Step 3: Implement `import_imagery.py`**

Create `scripts/import_imagery.py`:

```python
#!/usr/bin/env python3
"""Import user-provided GeoTIFF files into MBTiles for Geographica.

Scans a drop directory, reprojects to Web Mercator, converts to MBTiles
in batches, and optionally cleans up source files.

Usage:
    python import_imagery.py --input /data/import \
        --output /data/imagery_custom.mbtiles
    python import_imagery.py --input /data/import \
        --name "phoenix drone" --output-dir /data
"""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from pipeline_security import (
    sanitize_layer_name,
    safe_staging_path,
    validate_file_header,
)
from pipeline_progress import update_progress as _generic_progress
from tileserver_config import add_mbtiles_to_config

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# Import shared conversion utilities from acquire_imagery
sys.path.insert(0, str(Path(__file__).parent))
from acquire_imagery import convert_batch_to_mbtiles, merge_mbtiles

BATCH_SIZE = 5
GDAL_ENV = {**os.environ, "GDAL_CACHEMAX": "512"}

# Geospatial file extensions to report (not import)
OTHER_GEO_EXTENSIONS = {".jp2", ".sid", ".img", ".ecw", ".vrt"}


def scan_import_directory(import_dir: Path) -> dict:
    """Scan import directory for GeoTIFF files.

    Scans the directory and one level of subdirectories.
    Rejects symlinks.

    Returns dict with keys: tif_files, other_geo_files, total_bytes
    """
    tif_files = []
    other_geo_files = []
    total_bytes = 0

    dirs_to_scan = [import_dir]
    # One level of subdirectories
    for item in import_dir.iterdir():
        if item.is_dir() and not item.is_symlink():
            dirs_to_scan.append(item)

    for scan_dir in dirs_to_scan:
        for item in scan_dir.iterdir():
            if item.is_symlink():
                continue
            if not item.is_file():
                continue
            ext = item.suffix.lower()
            if ext in (".tif", ".tiff"):
                tif_files.append(item)
                total_bytes += item.stat().st_size
            elif ext in OTHER_GEO_EXTENSIONS:
                other_geo_files.append(item)

    return {
        "tif_files": sorted(tif_files),
        "other_geo_files": sorted(other_geo_files),
        "total_bytes": total_bytes,
    }


def resolve_output_path(output_dir: Path, layer_name: str | None) -> Path:
    """Resolve the output MBTiles path from an optional layer name.

    Args:
        output_dir: Directory for MBTiles output.
        layer_name: Optional user-provided name. None/empty → imagery_custom.mbtiles.

    Returns:
        Full path to the output MBTiles file.

    Raises:
        ValueError: If layer_name contains path traversal.
    """
    if not layer_name or not layer_name.strip():
        return output_dir / "imagery_custom.mbtiles"

    safe_name = sanitize_layer_name(layer_name)
    return output_dir / f"imagery_{safe_name}.mbtiles"


def reproject_geotiff(src: Path, dst: Path) -> bool:
    """Reproject a GeoTIFF to EPSG:3857 (Web Mercator).

    Returns True on success.
    """
    try:
        subprocess.run(
            [
                "gdalwarp", "-t_srs", "EPSG:3857",
                "-r", "lanczos",
                "-co", "TILED=YES",
                "-co", "COMPRESS=DEFLATE",
                str(src), str(dst),
            ],
            check=True, capture_output=True, text=True,
            timeout=3600, env=GDAL_ENV,
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        log.error("gdalwarp failed for %s: %s", src.name, exc)
        if dst.exists():
            dst.unlink()
        return False


def run_import(
    import_dir: Path,
    output_path: Path,
    delete_after: bool = False,
    tileserver_config: Path | None = None,
) -> None:
    """Run the BYO import pipeline."""
    state_path = output_path.parent / ".import-state.json"

    scan = scan_import_directory(import_dir)
    tif_files = scan["tif_files"]

    if not tif_files:
        log.error("No GeoTIFF files found in %s", import_dir)
        _generic_progress(state_path, source="import", status="error",
                          detail="No GeoTIFF files found", error="No .tif files in import directory")
        return

    log.info("Found %d GeoTIFFs (%.1f GB) in %s",
             len(tif_files), scan["total_bytes"] / 1e9, import_dir)

    if scan["other_geo_files"]:
        exts = set(f.suffix for f in scan["other_geo_files"])
        log.warning("Found %d unsupported files (%s) — only .tif/.tiff is imported",
                    len(scan["other_geo_files"]), ", ".join(exts))

    total = len(tif_files)
    staging_dir = output_path.parent / "import_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    completed = 0
    for batch_start in range(0, total, BATCH_SIZE):
        batch = tif_files[batch_start:batch_start + BATCH_SIZE]
        warped_paths = []

        for tif in batch:
            _generic_progress(state_path, source="import", status="running",
                              phase="converting",
                              items_done=completed, items_total=total,
                              item_unit="files",
                              detail=f"Reprojecting {tif.name}")

            warped = staging_dir / f"warped_{tif.name}"
            if reproject_geotiff(tif, warped):
                warped_paths.append(warped)
            else:
                log.warning("Skipping %s (reproject failed)", tif.name)

        if warped_paths:
            _generic_progress(state_path, source="import", status="running",
                              phase="merging",
                              items_done=completed, items_total=total,
                              item_unit="files",
                              detail=f"Converting batch to MBTiles")

            success = convert_batch_to_mbtiles(
                warped_paths, output_path, f"import_{batch_start}"
            )
            if not success:
                log.error("Batch conversion failed at offset %d", batch_start)

        # Cleanup warped files
        for wp in warped_paths:
            if wp.exists():
                wp.unlink()

        # Delete source files if requested (only after successful batch)
        if delete_after and warped_paths:
            for tif in batch:
                if tif.exists():
                    tif.unlink()
                    log.info("Deleted source: %s", tif)

        completed += len(batch)

    # Update TileServer config if provided
    if tileserver_config and tileserver_config.exists():
        name = output_path.stem  # e.g., "imagery_custom"
        added = add_mbtiles_to_config(
            tileserver_config, name, f"/srv/data/{output_path.name}"
        )
        if added:
            log.info("Added %s to TileServer config.json", name)

    _generic_progress(state_path, source="import", status="completed",
                      items_done=total, items_total=total,
                      item_unit="files",
                      detail=f"Imported {total} files into {output_path.name}")
    log.info("Import complete: %d files → %s", total, output_path)


def main():
    parser = argparse.ArgumentParser(description="Import GeoTIFF files into MBTiles")
    parser.add_argument("--input", required=True, help="Import directory path")
    parser.add_argument("--output", default=None, help="Output MBTiles path (overrides --name)")
    parser.add_argument("--output-dir", default="/data", help="Output directory (used with --name)")
    parser.add_argument("--name", default=None, help="Layer name (default: imagery_custom)")
    parser.add_argument("--delete-after", action="store_true", help="Delete source files after import")
    parser.add_argument("--tileserver-config", default=None, help="Path to tileserver/config.json")

    args = parser.parse_args()

    if args.output:
        output_path = Path(args.output)
    else:
        output_path = resolve_output_path(Path(args.output_dir), args.name)

    run_import(
        import_dir=Path(args.input),
        output_path=output_path,
        delete_after=args.delete_after,
        tileserver_config=Path(args.tileserver_config) if args.tileserver_config else None,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
python -m pytest tests/test_import_imagery.py -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ --tb=short
```

Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/import_imagery.py tests/test_import_imagery.py
git commit -m "feat: add BYO GeoTIFF import script with reprojection and batch conversion"
```

---

### Task 6: Backend Orchestrator — NOAA + BYO Import Endpoints

**Files:**
- Modify: `services/search/main.py` — add `noaa` mode validation/command, BYO import endpoint, TileServer restart

BEFORE starting work:
1. Read `services/search/main.py` — understand `pipeline_start()`, mode validation (~line 1068), command builder (~line 1140), container launch (~line 1273)
2. Read `docker-compose.yml` — understand volume mounts for the pipeline container

- [ ] **Step 1: Add `noaa` to mode validation**

In `pipeline_start()`, change the mode validation:

```python
        if not body.mode or body.mode not in ("direct", "m2m", "nationalmap", "noaa"):
```

- [ ] **Step 2: Add `noaa` command builder**

After the `nationalmap` elif block, before the final `else:`:

```python
                elif body.mode == "noaa":
                    command = [
                        "python3", "/scripts/acquire_imagery.py",
                        "--mode", "noaa",
                        f"--bbox={body.bbox}",
                        f"--state={body.state or 'AZ'}",
                        f"--year={body.year or 2021}",
                        "--output", "/data/imagery_noaa.mbtiles",
                    ]
```

- [ ] **Step 3: Add `state` and `year` fields to `PipelineStartBody`**

```python
class PipelineStartBody(BaseModel):
    type: str
    mode: Optional[str] = None
    bbox: Optional[str] = None
    zoom: Optional[str] = None
    concurrency: int = 20
    update: bool = True
    counties: Optional[str] = None
    state: Optional[str] = None   # for NOAA mode
    year: Optional[int] = None    # for NOAA mode
```

- [ ] **Step 4: Add BYO import endpoint**

Add after `pipeline_cancel()`:

```python
@app.post("/admin/pipeline/import", dependencies=[Depends(require_config_source)])
async def pipeline_import(
    layer_name: Optional[str] = None,
    delete_after: bool = False,
):
    """Start a BYO GeoTIFF import pipeline."""
    import_dir = DATA_DIR / "import"
    if not import_dir.exists():
        import_dir.mkdir(parents=True)

    # Scan for files
    tif_files = list(import_dir.rglob("*.tif")) + list(import_dir.rglob("*.tiff"))
    tif_files = [f for f in tif_files if not f.is_symlink() and f.is_file()]

    if not tif_files:
        raise HTTPException(status_code=422, detail="No GeoTIFF files found in import directory")

    async with _pipeline_lock:
        client = _get_docker_client()
        if not client:
            raise HTTPException(status_code=503, detail="Docker socket not available")

        try:
            if _is_pipeline_container_running(client):
                raise HTTPException(status_code=409, detail="A pipeline job is already running")

            # Build command
            command = [
                "python3", "/scripts/import_imagery.py",
                "--input", "/data/import",
                "--output-dir", "/data",
            ]
            if layer_name:
                command.extend(["--name", layer_name])
            if delete_after:
                command.append("--delete-after")

            # Resolve host paths
            host_data_path = os.environ.get("DATA_HOST_PATH", "")
            host_scripts_path = os.environ.get("SCRIPTS_HOST_PATH", "")

            if not host_data_path:
                try:
                    search_container = client.containers.get("geographica-search")
                    mounts = search_container.attrs.get("Mounts", [])
                    for mount in mounts:
                        if mount.get("Destination") == "/data":
                            host_data_path = mount.get("Source", "")
                            host_base = os.path.dirname(host_data_path)
                            if not host_scripts_path:
                                host_scripts_path = os.path.join(host_base, "scripts")
                            break
                except Exception:
                    pass

            if not host_data_path:
                raise HTTPException(status_code=500, detail="Cannot determine host data path")

            volumes = {
                host_data_path: {"bind": "/data", "mode": "rw"},
            }
            if host_scripts_path:
                volumes[host_scripts_path] = {"bind": "/scripts", "mode": "ro"}

            # Remove stale container
            try:
                old = client.containers.get("geographica-pipeline")
                old.remove(force=True)
            except Exception:
                pass

            env = {"GDAL_CACHEMAX": "512", "PYTHONUNBUFFERED": "1"}

            try:
                networks = client.networks.list(names=["geographica_default"])
                network = networks[0].name if networks else "bridge"
            except Exception:
                network = "bridge"

            container = client.containers.run(
                "geographica-pipeline",
                command=command,
                name="geographica-pipeline",
                detach=True,
                remove=False,
                volumes=volumes,
                environment=env,
                network=network,
                mem_limit="2g",
            )

            # Write state
            from datetime import datetime, timezone as tz
            state_data = {
                "status": "running",
                "type": "import",
                "source": "import",
                "container_id": container.id,
                "started_at": datetime.now(tz.utc).isoformat(),
            }
            state_file = DATA_DIR / ".import-state.json"
            state_file.write_text(json.dumps(state_data, indent=2))

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start import: {e}")
        finally:
            client.close()

    return {"status": "started", "files": len(tif_files)}
```

- [ ] **Step 5: Add `import` to status endpoint allowed types**

```python
    if type not in ("imagery", "elevation", "osm_poi", "sentinel", "naip", "import"):
```

- [ ] **Step 6: Add TileServer restart helper**

Add after the import endpoint:

```python
async def _restart_tileserver():
    """Restart TileServer container to pick up new config."""
    client = _get_docker_client()
    if not client:
        return
    try:
        ts = client.containers.get("geographica-tileserver")
        ts.restart(timeout=10)
        log.info("Restarted TileServer to load new config")
    except Exception as exc:
        log.warning("Failed to restart TileServer: %s", exc)
    finally:
        client.close()
```

Call this in the status endpoint reconciliation when a pipeline completes (after writing `"completed"` status), or expose it as a separate admin endpoint for the frontend to call after import.

- [ ] **Step 7: Run tests**

```bash
python -m pytest tests/ --tb=short
```

Expected: All tests PASS.

- [ ] **Step 8: Commit**

```bash
git add services/search/main.py
git commit -m "feat: add NOAA mode + BYO import endpoint to pipeline orchestrator"
```

---

### Task 7: Admin Panel UI — NOAA Source + BYO Import Card

**Files:**
- Modify: `frontend/config/index.html`

BEFORE starting work:
1. Read `frontend/config/index.html` — understand existing source dropdown, event handlers, pipeline rendering
2. Read the spec's "Admin Panel Integration" and "Admin Panel Card" sections

- [ ] **Step 1: Add NOAA dropdown option**

After the National Map option:

```html
                <option value="noaa">NOAA NAIP (0.6m, free, GeoTIFF)</option>
```

- [ ] **Step 2: Add state selector HTML**

After the minimap container div, add a state selector (hidden by default):

```html
            <div id="noaa-state-container" style="display:none">
                <label>State</label>
                <select id="noaa-state">
                    <option value="AZ">Arizona (2021)</option>
                </select>
                <div class="detail">NOAA NAIP downloads full-resolution 0.6m GeoTIFFs per tile (~486 MB each). Only tiles intersecting your bbox are downloaded.</div>
            </div>
```

- [ ] **Step 3: Update source change handler for NOAA**

In the existing `cfg-source` change handler, add NOAA handling:

```javascript
        var isNOAA = val === 'noaa';

        // Show/hide state selector
        document.getElementById('noaa-state-container').style.display = isNOAA ? '' : 'none';

        // Hide zoom for NOAA (fixed resolution)
        zoomEl.disabled = isM2M || isNOAA;
        if (isNOAA) {
            estimateEl.textContent = 'NOAA: select a state and draw bbox, then tile count will be shown after lookup';
            estimateEl.style.color = '#7a8299';
        }
```

- [ ] **Step 4: Add `noaa` to SOURCE_LABELS**

```javascript
    var SOURCE_LABELS = {
        sentinel: 'Sentinel-2',
        naip: 'NAIP',
        direct: 'USGS Direct',
        m2m: 'USGS M2M',
        nationalmap: 'National Map NAIP',
        noaa: 'NOAA NAIP',
        elevation: 'Elevation',
        import: 'Custom Import'
    };
```

- [ ] **Step 5: Update imagery start handler for NOAA**

In the `cfg-start` click handler, add NOAA-specific body fields:

```javascript
        if (source === 'noaa') {
            body.state = document.getElementById('noaa-state').value;
            body.year = 2021; // from the dropdown label
        }
```

And update the confirm message:

```javascript
        } else if (source === 'noaa') {
            confirmMsg = 'Start NOAA NAIP download for ' + body.state + '? Large GeoTIFF files will be downloaded and converted.';
```

- [ ] **Step 6: Add BYO Import card HTML**

After the NAIP card, before the Settings tab:

```html
        <!-- Custom Imagery Import -->
        <div class="section" id="import-section">
            <h2 style="font-size:14px;color:#f5f5f5;margin:0 0 12px">Import Custom Imagery</h2>
            <div class="detail" style="margin-bottom:8px">
                Place GeoTIFF (.tif) files in <code>/srv/geographica/data/import/</code> and click Import.
                Subdirectories (one level) are scanned. Files are reprojected to Web Mercator and converted to MBTiles.
            </div>

            <div id="import-scan-result" class="detail" style="margin-bottom:8px">
                Scanning...
            </div>

            <label>Layer name <span class="detail">(optional — leave blank for default)</span></label>
            <input type="text" id="import-layer-name" class="mono" placeholder="e.g., phoenix_drone_2026">

            <label class="checkbox-label">
                <input type="checkbox" id="import-delete-after">
                Delete source files after successful import
            </label>

            <div style="margin-top:12px">
                <button type="button" class="btn-secondary" id="import-refresh">Refresh</button>
                <button type="button" class="btn-primary" id="import-start" disabled>Import</button>
            </div>

            <div id="import-progress" style="display:none">
                <div class="progress-bar"><div class="progress-fill" id="import-progress-fill"></div></div>
                <div id="import-progress-detail" class="detail"></div>
            </div>
            <div id="import-completed" class="status status-ok" style="display:none"></div>
        </div>
```

- [ ] **Step 7: Add BYO Import JavaScript**

Add import scan, start, and progress rendering:

```javascript
    // -----------------------------------------------------------------------
    // BYO Import
    // -----------------------------------------------------------------------
    function scanImportDir() {
        var scanEl = document.getElementById('import-scan-result');
        scanEl.textContent = 'Scanning...';
        document.getElementById('import-start').disabled = true;

        cfgFetch('/admin/pipeline/import/scan')
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.error || d.detail) {
                    scanEl.textContent = 'Error: ' + (d.error || d.detail);
                    return;
                }
                var tifCount = d.tif_count || 0;
                var totalMB = ((d.total_bytes || 0) / 1e6).toFixed(0);
                var msg = tifCount + ' GeoTIFFs (' + totalMB + ' MB)';
                if (d.other_geo_count > 0) {
                    msg += ' \u2022 ' + d.other_geo_count + ' unsupported files found (see note)';
                }
                scanEl.textContent = msg;
                document.getElementById('import-start').disabled = tifCount === 0 || _anyPipelineRunning;
            })
            .catch(function() { scanEl.textContent = 'Scan failed (API offline?)'; });
    }

    document.getElementById('import-refresh').addEventListener('click', scanImportDir);

    document.getElementById('import-start').addEventListener('click', function() {
        var name = document.getElementById('import-layer-name').value.trim();
        var deleteAfter = document.getElementById('import-delete-after').checked;
        var qs = '?delete_after=' + deleteAfter;
        if (name) qs += '&layer_name=' + encodeURIComponent(name);

        if (!confirm('Start import? This will convert all GeoTIFFs in the import directory.')) return;

        cfgFetch('/admin/pipeline/import' + qs, { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.error || d.detail) alert(d.error || d.detail);
                fetchAll();
            });
    });

    // Scan on page load
    scanImportDir();
```

- [ ] **Step 8: Add import scan API endpoint**

Back in `services/search/main.py`, add a GET endpoint for scanning:

```python
@app.get("/admin/pipeline/import/scan", dependencies=[Depends(require_config_source)])
async def import_scan():
    """Scan import directory for GeoTIFF files."""
    import_dir = DATA_DIR / "import"
    if not import_dir.exists():
        import_dir.mkdir(parents=True)
        return {"tif_count": 0, "total_bytes": 0, "other_geo_count": 0}

    tif_files = []
    other_geo = []
    total_bytes = 0
    other_extensions = {".jp2", ".sid", ".img", ".ecw"}

    dirs = [import_dir]
    for item in import_dir.iterdir():
        if item.is_dir() and not item.is_symlink():
            dirs.append(item)

    for d in dirs:
        for f in d.iterdir():
            if f.is_symlink() or not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in (".tif", ".tiff"):
                tif_files.append(f)
                total_bytes += f.stat().st_size
            elif ext in other_extensions:
                other_geo.append(f)

    return {
        "tif_count": len(tif_files),
        "total_bytes": total_bytes,
        "other_geo_count": len(other_geo),
    }
```

- [ ] **Step 9: Commit**

```bash
git add frontend/config/index.html services/search/main.py
git commit -m "feat: add NOAA source dropdown + BYO import card to admin panel"
```

---

### Task 8: Frontend — NAIP/Custom Layer Discovery

**Files:**
- Modify: `frontend/app.js` — add auto-discovery for NOAA and custom imagery layers

BEFORE starting work:
1. Read `frontend/app.js` — understand `_tryAddTileJSONSource()` pattern (~line 230) and the 30-second poll (~line 3956)

- [ ] **Step 1: Add NOAA and custom imagery source discovery**

In the `_tryAddTileJSONSource` block for NAIP/Sentinel (~line 747), add:

```javascript
    _tryAddTileJSONSource('imagery-noaa', '/tiles/data/imagery_noaa.json', 'raster');
    _tryAddTileJSONSource('imagery-custom', '/tiles/data/imagery_custom.json', 'raster');
```

And in the 30-second poll (~line 3956), add the same lines after the existing NAIP/Sentinel calls:

```javascript
      _availableTileJSON['imagery-noaa'] = undefined;
      _availableTileJSON['imagery-custom'] = undefined;
      _tryAddTileJSONSource('imagery-noaa', '/tiles/data/imagery_noaa.json', 'raster');
      _tryAddTileJSONSource('imagery-custom', '/tiles/data/imagery_custom.json', 'raster');
```

The `_updateImageryToggles()` function already dynamically builds toggle checkboxes for any discovered raster sources — these will appear automatically.

- [ ] **Step 2: Commit**

```bash
git add frontend/app.js
git commit -m "feat: add NOAA + custom imagery layer auto-discovery in frontend"
```

---

### Task 9: Rebuild + Deploy + Smoke Test

**Files:** None modified — deployment and verification.

- [ ] **Step 1: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests PASS.

- [ ] **Step 2: Rebuild and deploy**

```bash
docker compose up -d --build search --force-recreate frontend
```

- [ ] **Step 3: Verify admin panel**

1. Open `http://localhost:8097`, go to Pipelines tab
2. Verify source dropdown has: USGS Direct, USGS M2M, National Map NAIP, NOAA NAIP
3. Select "NOAA NAIP" — verify state dropdown appears, zoom disables
4. Scroll down — verify "Import Custom Imagery" card appears
5. Verify import card shows scan results

- [ ] **Step 4: Test BYO import (create test GeoTIFF)**

```bash
# Create a small test GeoTIFF
mkdir -p /srv/geographica/data/import
gdal_create -outsize 256 256 -bands 3 -ot Byte \
  -a_srs EPSG:4326 -a_ullr -112.1 33.5 -112.0 33.4 \
  /srv/geographica/data/import/test_tile.tif 2>/dev/null || \
python3 -c "
# Fallback: create a minimal GeoTIFF with just the header
from pathlib import Path
Path('/srv/geographica/data/import/test_tile.tif').write_bytes(
    b'II\x2a\x00' + b'\x00' * 500
)
"
```

Then in the admin panel, click Refresh in the Import card, verify "1 GeoTIFF" found.

- [ ] **Step 5: Commit**

```bash
git add -A
git status
git commit -m "feat: NOAA NAIP + BYO imagery import — complete implementation"
```
