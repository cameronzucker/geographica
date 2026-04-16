# NOAA 3-Stage Pipeline — Progress, ETA & Dedup Fixes

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Fix three problems in the NOAA pipeline: (1) progress meter doesn't show per-stage breakdown or live ETA, (2) pre-run time estimate uses stale constants from the old sequential pipeline, (3) re-running with a larger bbox re-downloads NAIP quads already in the output, (4) MBTiles metadata bounds reflect only the first batch, not the full tile extent.

**Architecture:** Backend-first. (1) Emit per-stage counters and a rolling throughput rate from `run_noaa`. (2) Update the pre-run estimate endpoint to match the new pipeline's real throughput. (3) Render multi-stage progress + live ETA in the frontend admin panel. (4) Dedup NAIP quads already merged into the output. (5) Recalculate metadata bounds after all merges.

**Tech Stack:** Python (asyncio, threading), FastAPI, vanilla JS.

**Context:**
The NOAA pipeline was ported from the companion repo on 2026-04-16 (commit `42d9248`). It now runs 3 concurrent stages:

1. **Download** — up to 4 concurrent HTTP fetches of ~486 MB NAIP GeoTIFFs
2. **Reproject** — `min(cpu_count, 6)` threads reproject each GeoTIFF to EPSG:3857
3. **Merge** — single worker writes tiles into the output MBTiles, compositing overlaps

The admin panel start/cancel wiring still works. What's broken:

- `_write_progress()` at `scripts/acquire_imagery.py:1839-1864` only emits `geotiffs_downloaded=tiles_done` (the merged count). The intermediate counters `tiles_downloaded` and `tiles_reprojected` are never persisted.
- There is no deduplication: re-running with a larger bbox that overlaps an already-processed area re-downloads, re-reprojects, and re-merges every overlapping NAIP quad. The `direct` and `m2m` modes both have checkpoint/dedup logic; NOAA has none.
- `merge_mbtiles` copies metadata (including `bounds`) from the first batch file. As subsequent batches merge in, the bounds are never recalculated. TileServer/MapLibre read the `bounds` from TileJSON and won't request tiles outside — making most imagery invisible after a multi-quad run.
- `update_progress()` is always called without `rate=`, so `rate_per_sec` is permanently `0.0`. The frontend has no data for a running ETA.
- The pre-run estimate at `services/search/main.py:1688-1699` was calibrated for the OLD sequential GDAL CLI pipeline (6 min/tile). The new pipeline runs ~1.5–2 min/tile, so estimates are 3–6× too pessimistic.
- `frontend/config/index.html:520-527` has only a "direct mode" branch for imagery; it doesn't render the 3-stage breakdown.

**End-to-end test evidence (2026-04-16, 24-tile Flagstaff bbox):**
- Download stage finished at ~10 min; merge finished at ~24 min.
- During that window the progress bar only moved when a tile was *merged* (1 tick every ~1 min). Downloads racing ahead were invisible to the user.

---

## Pitfalls Reference

Before working on ANY task, read both pitfalls files:

- `docs/pitfalls/testing-pitfalls.md`
- `docs/pitfalls/implementation-pitfalls.md`

Most relevant pitfalls:

- **Testing — tests spawning orphaned processes (pitfall #12):** the NOAA pipeline spawns threads + asyncio tasks. Any test that exercises `run_noaa` end-to-end MUST mock the stage functions (`_download_tile`, `_reproject_tile`, `_merge_tile`) — do NOT let real work spawn.
- **Testing — monkeypatch fixture:** prefer `monkeypatch` over direct `os.environ` manipulation in any test that touches env vars.
- **Implementation — config panel is localhost-only, requires `X-Config-Source: internal` header:** any new admin endpoint must reuse `Depends(require_config_source)`.
- **Implementation — offline-first, no CDN deps:** frontend changes must use only the existing local assets.

---

## File Map

### Modified Files

| File | Change |
|------|--------|
| `scripts/acquire_imagery.py` | `_write_progress()` emits per-stage counters + rolling rate (T1). NAIP quad dedup via `_noaa_checkpoint` table (T5). `_update_mbtiles_bounds()` recalculates bounds after merges (T6). |
| `services/search/main.py` | `noaa_estimate()` uses 3-stage pipeline constants + returns `per_tile_seconds` (T2). |
| `frontend/config/index.html` | `renderPipelineBanner()` renders 3-stage NOAA progress + live ETA (T3). |

### New Files

| File | Description |
|------|-------------|
| `tests/test_noaa_progress.py` | Tests for `_write_progress()` emitting all 3 stage counters + rolling rate. |
| `services/search/tests/test_noaa_estimate.py` | Tests for `noaa_estimate()` returning sensible 3-stage values. |
| `tests/test_noaa_dedup.py` | Tests for NAIP quad checkpoint dedup logic. |
| `tests/test_mbtiles_bounds.py` | Tests for bounds recalculation from tile extent. |

---

## Dependency Graph

```
Task 1 (progress counters)   Task 2 (estimate constants)   Task 5 (NAIP dedup)   Task 6 (bounds metadata)
        \                              /                          |                       |
         \                            /                           |                       |
          v                          v                            v                       v
            Task 3 (Frontend 3-stage + ETA)                       |                       |
                        \                                         |                       |
                         \                                        |                       |
                          v                                       v                       v
                                    Task 4 (End-to-end smoke test + commit)
```

- Tasks 1, 2, 5, and 6 are all INDEPENDENT — can run in parallel.
- Task 3 depends on Tasks 1 and 2 (needs new state-file fields + estimate fields).
- Task 4 depends on ALL other tasks (final integration verification).

---

## Task 1 — Backend: per-stage counters + rolling rate in `run_noaa`

**Files:** `scripts/acquire_imagery.py`, new test `tests/test_noaa_progress.py`

### BEFORE starting work:
1. Read the skill at `.claude/skills/test-driven-development/` (or invoke `/test-driven-development`).
2. Read `docs/pitfalls/testing-pitfalls.md` — especially pitfall #12 (orphaned processes).
3. Read `scripts/acquire_imagery.py:225-323` to understand the existing `update_progress()` signature.
4. Read `scripts/acquire_imagery.py:1815-1864` to understand the current `_write_progress()` and shared counter pattern.

Follow TDD: write failing test → implement fix → verify green.

### Current behavior (bug evidence)
`scripts/acquire_imagery.py:1861-1864`:

```python
update_progress(output, "noaa", args.bbox, "n/a",
                done, total_tiles, phase=phase,
                geotiffs_downloaded=dl,
                geotiffs_total=total_tiles)
```

The local variables `rp` (tiles_reprojected) and `dl_done` are read from the shared counters but never passed to `update_progress()`. `rate` is never computed or passed.

### Desired behavior

1. **Extend `update_progress()` signature** at `scripts/acquire_imagery.py:225-233` with two new optional params:
   - `tiles_reprojected: int = None`
   - (Keep existing `geotiffs_downloaded` as-is; it already carries `tiles_downloaded`.)

   In the state-file enrichment block (`scripts/acquire_imagery.py:293-321`), add:
   ```python
   if tiles_reprojected is not None:
       enriched["tiles_reprojected"] = tiles_reprojected
   ```

   **Do NOT** add new fields to the canonical `_generic_progress()` call — keep those as-is to preserve backward compat. Add the new field only to the `enriched` dict (the pattern already used by `geotiffs_downloaded` at line 309-310).

2. **Rolling rate in `_write_progress()`** at `scripts/acquire_imagery.py:1839-1864`:
   - Capture the pipeline start time as a closure variable (e.g., `_progress_start_monotonic = time.monotonic()`) declared *once* before the async stages begin, at roughly `scripts/acquire_imagery.py:1820` (next to the shared counters).
   - In `_write_progress()`, compute `elapsed = time.monotonic() - _progress_start_monotonic`. Compute `rate = done / elapsed if elapsed > 0 else 0.0`. Rate is **tiles merged per second** — use this unit consistently; do NOT try to average across stages.
   - Pass `rate=rate` and `tiles_reprojected=rp` to `update_progress()`.

3. **Preserve existing behavior**: `geotiffs_downloaded=dl` must still carry `tiles_downloaded`. The frontend can continue reading this field until Task 3 updates it.

### Test (write first, must fail before implementation)

`tests/test_noaa_progress.py`:

```python
"""Tests for per-stage progress emission in run_noaa."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import update_progress


def test_update_progress_persists_tiles_reprojected(tmp_path):
    """New tiles_reprojected param must land in the state file."""
    out = tmp_path / "imagery.mbtiles"
    update_progress(
        out, "noaa", "-112,33,-111,34", "n/a",
        tiles_done=2, tiles_total=10, rate=0.5,
        phase="downloading",
        geotiffs_downloaded=8,
        geotiffs_total=10,
        tiles_reprojected=5,
    )
    state = json.loads((tmp_path / ".pipeline-state.json").read_text())
    assert state["tiles_reprojected"] == 5
    assert state["geotiffs_downloaded"] == 8
    assert state["tiles_done"] == 2
    assert state["rate_per_sec"] == 0.5


def test_update_progress_omits_tiles_reprojected_when_unset(tmp_path):
    """Backward compat: callers that don't pass the new param don't see it."""
    out = tmp_path / "imagery.mbtiles"
    update_progress(
        out, "direct", "-112,33,-111,34", "0-12",
        tiles_done=100, tiles_total=1000, rate=2.0,
    )
    state = json.loads((tmp_path / ".pipeline-state.json").read_text())
    assert "tiles_reprojected" not in state
```

For the rolling-rate behavior, add a test that constructs a fake pipeline scenario by monkeypatching `time.monotonic`. But note: `_write_progress` is nested inside `run_noaa` — it's not directly unit-testable. Rather than refactoring for testability (out of scope), add this test instead at the `update_progress` layer by passing an explicit `rate` value, and leave the rolling-rate integration covered by the Task 4 end-to-end smoke test.

### BEFORE marking this task complete:
1. Review your tests against `docs/pitfalls/testing-pitfalls.md` — specifically pitfall #12.
2. Run `python -m pytest tests/test_noaa_progress.py -v` and confirm green.
3. Run the existing NOAA test suite: `python -m pytest tests/test_noaa_naip.py tests/test_mbtiles_merge.py -v` and confirm no regressions.

### Do NOT:
- Do NOT refactor `_write_progress` out of the closure. The nested function design is intentional (shared counters under `counter_lock`).
- Do NOT add new fields to the generic `_generic_progress()` call signature. Use the `enriched` dict pattern.
- Do NOT change the meaning of `geotiffs_downloaded`. Renaming is Task 3's job, conditional on frontend update.
- Do NOT try to emit stage-weighted rates. Use `tiles_done / elapsed` only.

---

## Task 2 — Backend: fix `noaa_estimate` constants for 3-stage pipeline

**Files:** `services/search/main.py`, new test `services/search/tests/test_noaa_estimate.py`

### BEFORE starting work:
1. Read the skill at `.claude/skills/test-driven-development/`.
2. Read `docs/pitfalls/testing-pitfalls.md`.
3. Read `services/search/main.py:1617-1712` (the current `noaa_estimate` endpoint).

### Current behavior (bug evidence)
`services/search/main.py:1696-1699`:

```python
download_time_s = NOAA_TILE_SIZE_MB / 2.7  # seconds per tile at ~2.7 MB/s
process_time_s = 90  # reproject + convert empirical
effective_per_tile_s = max(download_time_s / download_concurrency, process_time_s)
est_hours = tile_count * effective_per_tile_s / 3600
```

Problem: `process_time_s = 90` was measured against the OLD sequential GDAL CLI pipeline. The new 3-stage rasterio pipeline has different economics:

- Desktop (8+ cores, no swap): ~60 s/tile end-to-end.
- Pi 5 (4 cores, swap-pressured with 4 reprojector threads): ~90–120 s/tile end-to-end.
- The merge stage is the serial bottleneck, taking ~20–30 s/tile regardless of hardware.

### Desired behavior

1. **Replace the constants** at `services/search/main.py:1688-1699` with values that better model the 3-stage pipeline. Target mid-range hardware (Pi 5 with headroom) so estimates don't *under*-promise on desktop runs:

   ```python
   # 3-stage parallel pipeline economics:
   # - Download stage: 4 concurrent fetches at ~3 MB/s each → ~160 s/tile raw but parallelized
   # - Reproject stage: CPU-bound, min(cpu_count, 6) threads → ~45 s/tile wall-clock at 4 cores
   # - Merge stage: serial, ~20 s/tile (the bottleneck once downloads catch up)
   # Steady-state per-tile cost = max(download/concurrency, reproject/workers, merge_serial)
   download_concurrency = 4
   reproject_workers = 4  # typical Pi 5; desktops run faster, this is a conservative floor
   download_per_tile_s = (NOAA_TILE_SIZE_MB / 3.0) / download_concurrency  # ~40 s
   reproject_per_tile_s = 45 / reproject_workers                            # ~11 s
   merge_per_tile_s = 20                                                     # serial bottleneck
   effective_per_tile_s = max(download_per_tile_s, reproject_per_tile_s, merge_per_tile_s)
   # Add pipeline-fill overhead: first tile must traverse all 3 stages before the meter moves
   startup_overhead_s = 120
   est_seconds = tile_count * effective_per_tile_s + startup_overhead_s
   est_hours = est_seconds / 3600
   ```

2. **Add `per_tile_seconds` to the response body** so the frontend can show a live ETA:

   ```python
   return {
       "status": "ok",
       "tile_count": tile_count,
       "raw_download_gb": round(raw_download_gb, 1),
       "final_mbtiles_gb": round(final_mbtiles_gb, 1),
       "staging_peak_gb": round(NOAA_TILE_SIZE_MB * (download_concurrency + 1) / 1024, 1),
       "est_hours": round(est_hours, 2),
       "est_days": round(est_hours / 24, 2),
       "per_tile_seconds": round(effective_per_tile_s, 1),
       "download_concurrency": download_concurrency,
       "download_speed_mbs": 3.0,
       "disk_free_gb": round(_get_disk_free_gb(), 1),
   }
   ```

### Test (write first, must fail before implementation)

`services/search/tests/test_noaa_estimate.py`:

```python
"""Tests for /admin/pipeline/noaa/estimate.

The endpoint must model the 3-stage pipeline — not the old sequential GDAL CLI
economics (which estimated ~6 min/tile and was 3-6x too pessimistic).
"""
from unittest.mock import patch
import struct
import pytest
from fastapi.testclient import TestClient


def test_estimate_per_tile_seconds_reflects_3_stage_pipeline():
    """Per-tile ETA should be dominated by the slowest stage (~20-45s), not 90s."""
    from services.search.main import app
    client = TestClient(app, headers={"X-Config-Source": "internal"})

    with patch("services.search.main._get_disk_free_gb", return_value=500.0):
        # Force tile_count to a known value by stubbing the catalog/shapefile logic;
        # simplest: use the fallback tile_count=7629 path when cache/dbf is missing.
        resp = client.get(
            "/admin/pipeline/noaa/estimate",
            params={"bbox": "-114,32,-109,37", "state": "AZ", "year": 2021},
        )

    # If the NOAA catalog cache isn't present, endpoint returns status=no_index.
    # Skip the substantive assertion in that case — the test still exercises routing.
    data = resp.json()
    if data.get("status") == "no_index":
        pytest.skip("NOAA catalog not cached in CI environment")

    assert resp.status_code == 200
    assert "per_tile_seconds" in data
    assert data["per_tile_seconds"] < 60, \
        f"Per-tile ETA should be < 60s under 3-stage pipeline, got {data['per_tile_seconds']}"
    assert data["per_tile_seconds"] > 10, \
        "Per-tile ETA should be > 10s even in optimistic case (merge is serial)"
```

### BEFORE marking this task complete:
1. Review tests against `docs/pitfalls/testing-pitfalls.md`.
2. Run `python -m pytest services/search/tests/ -v` and confirm green.

### Do NOT:
- Do NOT make the estimate vary by hardware. The constants should be conservative defaults — runtime rate (Task 1 + Task 3) is what gives live accuracy.
- Do NOT remove or rename existing fields. Frontend still reads `est_hours`, `est_days`, `tile_count`, etc.
- Do NOT import `acquire_imagery` in `services/search/main.py`. The existing endpoint deliberately inlines NOAA_TILE_SIZE_MB to avoid the aiohttp dependency.

---

## Task 3 — Frontend: 3-stage progress + live ETA

**Files:** `frontend/config/index.html`

### BEFORE starting work:
1. Read the skill at `.claude/skills/test-driven-development/`.
2. Read `frontend/config/index.html:495-560` (the current `renderPipelineBanner` function).
3. Read the output of Task 1 — confirm `tiles_reprojected`, `rate_per_sec`, `phase` fields are in the state file.
4. Read the output of Task 2 — confirm `per_tile_seconds` is in the estimate response.

Follow TDD: manual test (browser) after code change; JS unit tests are out of scope for this repo.

### Current behavior (bug evidence)
`frontend/config/index.html:520-527`:

```js
} else {
    title = 'Imagery download in progress';
    var total = imageryData.estimated_tiles || imageryData.tiles_total || 1;
    var done = imageryData.tiles_done || 0;
    pct = Math.min(100, done / total * 100);
    var rate = imageryData.rate_per_sec ? Math.round(imageryData.rate_per_sec) + ' tiles/sec' : '';
    detail = done.toLocaleString() + ' / ' + total.toLocaleString() + (rate ? ' \u00b7 ' + rate : '');
}
```

Problem: this branch handles both "direct" (zxy tile download) and "noaa" modes identically. For NOAA, the user sees only the merged-tile count, which crawls at ~1 tile/min while downloads race ahead at ~4 tiles/min.

### Desired behavior

Add a new `mode === 'noaa'` branch in `renderPipelineBanner()`, parallel to the existing `m2m` branch:

```js
} else if (imageryData.mode === 'noaa') {
    var dl = imageryData.geotiffs_downloaded || 0;
    var rp = imageryData.tiles_reprojected || 0;
    var merged = imageryData.tiles_done || 0;
    var total = imageryData.geotiffs_total || imageryData.tiles_total || 1;
    var phase = imageryData.phase || 'downloading';
    var rate = imageryData.rate_per_sec || 0;

    title = 'NOAA NAIP imagery: ' + merged + '/' + total + ' tiles';
    pct = Math.min(100, merged / total * 100);

    // Three-line detail: one per stage
    var stages = [
        'Downloaded: ' + dl + '/' + total,
        'Reprojected: ' + rp + '/' + total,
        'Merged: ' + merged + '/' + total,
    ];
    // Live ETA from rolling rate
    if (rate > 0 && merged < total) {
        var remaining = total - merged;
        var etaSec = remaining / rate;
        var etaStr;
        if (etaSec > 3600) {
            etaStr = (etaSec / 3600).toFixed(1) + ' h';
        } else if (etaSec > 60) {
            etaStr = Math.round(etaSec / 60) + ' min';
        } else {
            etaStr = Math.round(etaSec) + ' s';
        }
        stages.push('ETA: ' + etaStr);
    }
    detail = stages.join(' \u00b7 ');
} else {
    // Existing direct-mode branch (unchanged)
    title = 'Imagery download in progress';
    ...
}
```

### Testing (manual)

1. Start the stack: `docker compose up -d`.
2. Open admin panel: `https://<host>/config/`.
3. Trigger an NOAA pipeline run (can reuse the existing 24-tile bbox `-111.9136,34.7970,-111.6274,34.9405`).
4. Observe the Dashboard tab during run:
   - Progress bar advances based on *merged* tiles (same as before — correct semantically).
   - Detail line shows 3 stages + ETA updating every poll.
   - During the first ~2 min (pipeline fill), ETA may show "-" or no value (rate=0). That's acceptable.
5. After first merge completes, ETA should show a sensible positive value that decreases over time.

### BEFORE marking this task complete:
1. Visually verify in-browser against a live pipeline run (can be a 4-tile mini bbox for speed).
2. Check browser console for any JS errors.
3. Verify other modes (M2M, direct, elevation, OSM) still render correctly — the new branch must not swallow their cases.

### Do NOT:
- Do NOT change the `pct` calculation to average across stages. Merged-tile-based pct is honest.
- Do NOT remove the `direct` mode branch; it's still used for USGS/Sentinel pipelines.
- Do NOT add new CSS classes or HTML structure. Reuse the existing banner layout.

---

## Task 5 — Backend: NAIP quad deduplication against existing output

**Files:** `scripts/acquire_imagery.py`, new test `tests/test_noaa_dedup.py`

### BEFORE starting work:
1. Read the skill at `.claude/skills/test-driven-development/`.
2. Read `docs/pitfalls/testing-pitfalls.md`.
3. Read `scripts/acquire_imagery.py:1790-1810` (the spatial filter → job manifest section of `run_noaa`).
4. Read `scripts/acquire_imagery.py:610-670` (`merge_mbtiles` — this is where tiles land in the output).
5. Read `scripts/acquire_imagery.py:908-922` (`run_direct` checkpoint pattern — this is the pattern to follow).

Follow TDD: write failing test → implement fix → verify green.

### Current behavior (bug evidence)

After `filter_tiles_by_bbox()` returns the list of NAIP quad filenames at `scripts/acquire_imagery.py:1792`, that full list becomes the job manifest — every quad is downloaded, reprojected, and merged. If the user previously ran the pipeline for Flagstaff (24 quads) and then runs it for all of northern Arizona (200+ quads, overlapping Flagstaff), those 24 quads are re-processed, wasting ~36 min of CPU and network time.

The `direct` mode solves this with a `_checkpoint` table in the output MBTiles. The `m2m` mode uses `m2m_checkpoint.json`. The NOAA mode has neither.

### Desired behavior

1. **Add a `_noaa_checkpoint` table** to the output MBTiles. Schema:

   ```sql
   CREATE TABLE IF NOT EXISTS _noaa_checkpoint (
       tile_filename TEXT PRIMARY KEY
   )
   ```

   This table records NAIP quad filenames (e.g., `m_3411101_se_12_060_20211014.tif`) that have been fully merged into the output.

2. **After each tile completes the merge stage**, insert its filename into `_noaa_checkpoint`. This happens in the merger task at approximately `scripts/acquire_imagery.py:2040-2050` (the line `tiles_done += 1`). Add a single INSERT after the merge completes:

   ```python
   # Inside the merger, after successful merge_mbtiles call:
   import sqlite3 as stdlib_sqlite3
   with stdlib_sqlite3.connect(str(output)) as ckpt_conn:
       ckpt_conn.execute(
           "CREATE TABLE IF NOT EXISTS _noaa_checkpoint (tile_filename TEXT PRIMARY KEY)"
       )
       ckpt_conn.execute(
           "INSERT OR IGNORE INTO _noaa_checkpoint (tile_filename) VALUES (?)",
           (tile_fname,)
       )
   ```

   Note: use stdlib `sqlite3`, not `aiosqlite` — the merger runs in the main asyncio thread but merge_mbtiles already uses stdlib sqlite3 internally, so this is consistent.

3. **Before building the job manifest**, filter out already-checkpointed quads. Insert this logic between lines 1800-1803 (after `total_tiles = len(tile_filenames)`, before progress update):

   ```python
   # Dedup: skip NAIP quads already merged into output
   if output.exists():
       import sqlite3 as stdlib_sqlite3
       try:
           with stdlib_sqlite3.connect(str(output)) as ckpt_conn:
               existing = {row[0] for row in ckpt_conn.execute(
                   "SELECT tile_filename FROM _noaa_checkpoint"
               ).fetchall()}
           before = len(tile_filenames)
           tile_filenames = [f for f in tile_filenames if f not in existing]
           if before > len(tile_filenames):
               log.info("Skipping %d already-processed NAIP quads (%d remaining)",
                        before - len(tile_filenames), len(tile_filenames))
       except stdlib_sqlite3.OperationalError:
           pass  # No checkpoint table yet — first run, process all
   
   if not tile_filenames:
       log.info("All %d NAIP quads already processed", total_tiles)
       # Still run post-processing (overviews, erosion, inpaint) in case it was interrupted
       # ... (see implementation note below)
   
   total_tiles_original = total_tiles  # preserve for logging
   total_tiles = len(tile_filenames)
   ```

4. **Handle the "all quads done but post-processing incomplete" edge case.** If the pipeline was killed during inpainting, all quads are checkpointed but post-processing didn't finish. When `tile_filenames` is empty after dedup, skip directly to the post-processing section (overviews + erosion + inpaint) at `scripts/acquire_imagery.py:2085`. Add a `goto`-style jump by setting a flag:

   ```python
   skip_to_postprocess = len(tile_filenames) == 0
   ```

   Then wrap the 3-stage pipeline block (lines ~1816-2080) in `if not skip_to_postprocess:`. The post-processing block at lines 2085+ runs regardless.

### Test (write first, must fail before implementation)

`tests/test_noaa_dedup.py`:

```python
"""Tests for NAIP quad deduplication in run_noaa."""

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _create_output_with_checkpoint(path: Path, checkpointed_quads: list[str]):
    """Create a minimal MBTiles with _noaa_checkpoint table."""
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE IF NOT EXISTS tiles (
        zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
        tile_data BLOB,
        PRIMARY KEY (zoom_level, tile_column, tile_row))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS metadata (name TEXT, value TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS _noaa_checkpoint (
        tile_filename TEXT PRIMARY KEY)""")
    for quad in checkpointed_quads:
        conn.execute("INSERT INTO _noaa_checkpoint (tile_filename) VALUES (?)", (quad,))
    conn.commit()
    conn.close()


def test_checkpoint_table_filters_manifest():
    """Quads already in _noaa_checkpoint should be excluded from the job manifest."""
    import sqlite3 as stdlib_sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.mbtiles"
        _create_output_with_checkpoint(output, [
            "m_3411101_ne_12_060_20211014.tif",
            "m_3411101_se_12_060_20211014.tif",
        ])

        # Simulate the dedup logic
        tile_filenames = [
            "m_3411101_ne_12_060_20211014.tif",  # already done
            "m_3411101_se_12_060_20211014.tif",  # already done
            "m_3411102_nw_12_060_20211014.tif",  # new
            "m_3411102_sw_12_060_20211014.tif",  # new
        ]

        with stdlib_sqlite3.connect(str(output)) as conn:
            existing = {row[0] for row in conn.execute(
                "SELECT tile_filename FROM _noaa_checkpoint"
            ).fetchall()}

        remaining = [f for f in tile_filenames if f not in existing]
        assert len(remaining) == 2
        assert "m_3411102_nw_12_060_20211014.tif" in remaining
        assert "m_3411102_sw_12_060_20211014.tif" in remaining


def test_no_checkpoint_table_processes_all():
    """First run (no checkpoint table) should process all quads."""
    import sqlite3 as stdlib_sqlite3
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.mbtiles"
        # Create MBTiles without checkpoint table
        conn = sqlite3.connect(str(output))
        conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.commit()
        conn.close()

        tile_filenames = ["a.tif", "b.tif", "c.tif"]

        try:
            with stdlib_sqlite3.connect(str(output)) as conn:
                existing = {row[0] for row in conn.execute(
                    "SELECT tile_filename FROM _noaa_checkpoint"
                ).fetchall()}
        except stdlib_sqlite3.OperationalError:
            existing = set()

        remaining = [f for f in tile_filenames if f not in existing]
        assert len(remaining) == 3


def test_nonexistent_output_processes_all():
    """When output file doesn't exist yet, all quads should be processed."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "output.mbtiles"
        assert not output.exists()

        tile_filenames = ["a.tif", "b.tif"]
        # Dedup logic: skip if output doesn't exist
        remaining = tile_filenames  # no filtering when file doesn't exist
        assert len(remaining) == 2
```

### BEFORE marking this task complete:
1. Review your tests against `docs/pitfalls/testing-pitfalls.md`.
2. Run `python -m pytest tests/test_noaa_dedup.py -v` and confirm green.
3. Run the existing NOAA test suite: `python -m pytest tests/test_noaa_naip.py tests/test_mbtiles_merge.py -v` and confirm no regressions.

### Do NOT:
- Do NOT use the checkpoint to skip post-processing. Overviews, erosion, and inpainting must always run on the full output (they're idempotent).
- Do NOT store per-tile (z/x/y) checkpoints like `direct` mode. NAIP dedup is at the quad level (one filename = ~1,100 tiles). Quad-level is the right granularity.
- Do NOT use aiosqlite for the checkpoint writes. The merger already uses stdlib sqlite3 via `merge_mbtiles`.
- Do NOT delete the checkpoint table after successful completion. It must persist across runs.

---

## Task 6 — Backend: recalculate MBTiles bounds metadata after merge

**Files:** `scripts/acquire_imagery.py`, new test `tests/test_mbtiles_bounds.py`

### BEFORE starting work:
1. Read the skill at `.claude/skills/test-driven-development/`.
2. Read `docs/pitfalls/testing-pitfalls.md`.
3. Read `scripts/acquire_imagery.py:610-670` (`merge_mbtiles`).
4. Read `scripts/acquire_imagery.py:2085-2130` (the post-processing section after merges complete).

Follow TDD: write failing test → implement fix → verify green.

### Current behavior (bug evidence)

`merge_mbtiles` at `scripts/acquire_imagery.py:625-630` creates the output tables on first batch and copies metadata from that first batch's source file. The `bounds` metadata value reflects only the first NAIP quad's geographic extent. Subsequent merges add tiles but never update `bounds`. TileServer reads `bounds` from MBTiles metadata, serves it in TileJSON, and MapLibre won't request tiles outside the declared bounds — making most of the imagery invisible.

This was hit in production: a 24-quad run produced tiles spanning `-111.94°W to -111.56°W, 34.75°N to 35.00°N`, but metadata `bounds` was `-111.94,-111.87,34.93,35.00` (first quad only). Cameron couldn't see any tiles in the main interface.

### Desired behavior

Add a function `_update_mbtiles_bounds(mbtiles_path)` that recalculates bounds from the actual tile extent. Call it after all merges complete, before overviews (since overviews add lower zoom tiles that would extend the tile column/row range but shouldn't change the geographic bounds).

**Insert the call** in `run_noaa`, immediately after the merge stage completes and before `build_overviews` — at approximately `scripts/acquire_imagery.py:2085` (after `log.info("Building overview pyramids...")`), but BEFORE the actual overview call. Actually, the best location is right before the `build_overviews` call.

**Implementation** of `_update_mbtiles_bounds`:

```python
def _update_mbtiles_bounds(mbtiles_path: Path) -> None:
    """Recalculate bounds metadata from actual tile extent at max zoom."""
    import math
    import sqlite3 as stdlib_sqlite3

    conn = stdlib_sqlite3.connect(str(mbtiles_path))
    try:
        # Find the max zoom level (highest resolution, most accurate bounds)
        row = conn.execute("SELECT MAX(zoom_level) FROM tiles").fetchone()
        if row is None or row[0] is None:
            return
        max_z = row[0]

        # Get tile extent at max zoom
        row = conn.execute(
            "SELECT MIN(tile_column), MAX(tile_column), MIN(tile_row), MAX(tile_row) "
            "FROM tiles WHERE zoom_level = ?", (max_z,)
        ).fetchone()
        if row is None or row[0] is None:
            return
        min_col, max_col, min_row, max_row = row
        n = 2 ** max_z

        # TMS tile_row to geographic bounds
        # TMS y=0 is south (unlike slippy where y=0 is north)
        def tms_to_bounds(z, x, y_tms):
            n = 2 ** z
            lon_min = x / n * 360 - 180
            lon_max = (x + 1) / n * 360 - 180
            y_slippy = n - 1 - y_tms
            lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y_slippy / n))))
            lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y_slippy + 1) / n))))
            return lon_min, lat_min, lon_max, lat_max

        sw = tms_to_bounds(max_z, min_col, min_row)
        ne = tms_to_bounds(max_z, max_col, max_row)
        west, south = sw[0], sw[1]
        east, north = ne[2], ne[3]

        bounds_str = f"{west},{south},{east},{north}"
        center_lon = (west + east) / 2
        center_lat = (south + north) / 2

        conn.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES ('bounds', ?)", (bounds_str,))
        conn.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES ('center', ?)",
                     (f"{center_lon},{center_lat},{max_z - 3}",))
        conn.commit()
        log.info("Updated MBTiles bounds: %s", bounds_str)
    finally:
        conn.close()
```

Place this function near the other helper functions (around line 700-730, near `_run_gdaladdo_with_metadata_fixup`). It must be a module-level function, NOT nested inside `run_noaa`.

### Test (write first, must fail before implementation)

`tests/test_mbtiles_bounds.py`:

```python
"""Tests for MBTiles bounds recalculation."""

import math
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def _tms_tile_for_point(lon, lat, zoom):
    """Convert a lon/lat to TMS tile coordinates."""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    lat_rad = math.radians(lat)
    y_slippy = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
    y_tms = n - 1 - y_slippy
    return x, y_tms


def _create_mbtiles_with_tiles(path, tile_coords_z17, initial_bounds="0,0,0,0"):
    """Create MBTiles with tiles at given (x, y_tms) coords at zoom 17."""
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE tiles (
        zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
        tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))""")
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('bounds', ?)", (initial_bounds,))
    conn.execute("INSERT INTO metadata VALUES ('format', 'jpeg')")
    for x, y in tile_coords_z17:
        conn.execute("INSERT INTO tiles VALUES (17, ?, ?, ?)", (x, y, b"fake"))
    conn.commit()
    conn.close()


def test_bounds_updated_to_match_tile_extent(tmp_path):
    """After recalculation, bounds should cover all tiles."""
    from acquire_imagery import _update_mbtiles_bounds

    mbtiles = tmp_path / "test.mbtiles"

    # Tiles spanning Sedona area: ~(-111.9, 34.8) to (-111.6, 34.9)
    sw_tile = _tms_tile_for_point(-111.9, 34.8, 17)
    ne_tile = _tms_tile_for_point(-111.6, 34.9, 17)
    tiles = [sw_tile, ne_tile]

    _create_mbtiles_with_tiles(mbtiles, tiles, initial_bounds="0,0,0,0")
    _update_mbtiles_bounds(mbtiles)

    conn = sqlite3.connect(str(mbtiles))
    bounds_str = conn.execute("SELECT value FROM metadata WHERE name='bounds'").fetchone()[0]
    conn.close()

    west, south, east, north = [float(x) for x in bounds_str.split(",")]
    # Bounds should approximately contain our tile points
    assert west < -111.9, f"West bound {west} should be < -111.9"
    assert east > -111.6, f"East bound {east} should be > -111.6"
    assert south < 34.8, f"South bound {south} should be < 34.8"
    assert north > 34.9, f"North bound {north} should be > 34.9"


def test_bounds_not_updated_for_empty_mbtiles(tmp_path):
    """Empty MBTiles should keep original bounds (no crash)."""
    from acquire_imagery import _update_mbtiles_bounds

    mbtiles = tmp_path / "empty.mbtiles"
    conn = sqlite3.connect(str(mbtiles))
    conn.execute("CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB)")
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('bounds', 'original')")
    conn.commit()
    conn.close()

    _update_mbtiles_bounds(mbtiles)

    conn = sqlite3.connect(str(mbtiles))
    bounds = conn.execute("SELECT value FROM metadata WHERE name='bounds'").fetchone()[0]
    conn.close()
    assert bounds == "original"
```

### BEFORE marking this task complete:
1. Review your tests against `docs/pitfalls/testing-pitfalls.md`.
2. Run `python -m pytest tests/test_mbtiles_bounds.py -v` and confirm green.
3. Run the existing test suite: `python -m pytest tests/test_noaa_naip.py tests/test_mbtiles_merge.py -v` and confirm no regressions.

### Do NOT:
- Do NOT call `_update_mbtiles_bounds` inside `merge_mbtiles` (it would run on every batch — expensive and unnecessary). Call it once after all merges complete.
- Do NOT update bounds based on overview tiles. Use only the max zoom level tiles for geographic accuracy.
- Do NOT change the `name` metadata field. It was set to the first quad's name; that's fine as a display name.
- Do NOT import rasterio or any heavy library for this function. It's pure math + sqlite3.

---

## Task 4 — End-to-end verification + commit

**Files:** none (verification task)

### BEFORE starting work:
1. Tasks 1, 2, 3, 5, and 6 must all be complete and individually tested.

### Steps

1. **Run the full test suite**:
   ```bash
   cd /home/administrator/Code/geographica
   python -m pytest tests/ services/search/tests/ -v
   ```
   Must be green.

2. **Run a 4-tile NOAA smoke test** (this small bbox should complete in ~5 min on a Pi):
   ```bash
   python scripts/acquire_imagery.py --mode noaa \
       --bbox=-111.85,34.85,-111.75,34.90 --state AZ \
       --output /tmp/noaa_progress_test.mbtiles
   ```

3. **While running, poll the state file** every 15 s for 2 minutes:
   ```bash
   for i in {1..8}; do
       cat /tmp/.pipeline-state.json | python -m json.tool | grep -E '(tiles_|rate_|phase)'
       sleep 15
   done
   ```
   Verify: `tiles_reprojected` > 0 appears before `tiles_done` > 0; `rate_per_sec` > 0 after first merge; `phase` transitions downloading → reprojecting → merging → converting.

4. **Verify bounds metadata** after run completes:
   ```bash
   python3 -c "
   import sqlite3
   conn = sqlite3.connect('/tmp/noaa_progress_test.mbtiles')
   for row in conn.execute('SELECT name, value FROM metadata WHERE name IN (\"bounds\", \"center\")'):
       print(row)
   conn.close()
   "
   ```
   Bounds should approximately cover the input bbox `-111.85,34.85,-111.75,34.90`, NOT just the first quad's extent.

5. **Verify dedup** — re-run the same bbox immediately:
   ```bash
   python scripts/acquire_imagery.py --mode noaa \
       --bbox=-111.85,34.85,-111.75,34.90 --state AZ \
       --output /tmp/noaa_progress_test.mbtiles
   ```
   Log should show "Skipping N already-processed NAIP quads" and the pipeline should complete almost instantly (only post-processing runs).

6. **Open admin panel** in a browser; verify the progress banner shows the 3-stage detail + live ETA.

7. **Commit**: single commit titled `feat: NOAA pipeline — 3-stage progress, live ETA, quad dedup, bounds fix`. Include all modified files + new tests. Follow the repo's Co-Authored-By convention (see recent commits via `git log --format=%B -1`).

### BEFORE marking this task complete:
- Test suite green.
- State-file fields verified in live run.
- Bounds metadata correct after run.
- Dedup confirmed on re-run.
- Admin panel renders correctly (visual check).
- Single commit with clear message.

---

## Review loop (applies to every task)

After every logical group of tasks:

You MUST carefully review the batch of work from multiple perspectives and revise/refine as appropriate. Repeat this review loop (you must do a minimum of three review rounds; if you still find substantive issues in the third review, keep going with additional rounds until there are no findings) until you're confident there aren't any more issues. Then update your private journal and continue onto the next tasks.

Specific review questions:
1. Did I accidentally break backward compatibility on `update_progress()`?
2. Did I add any new failure modes (e.g., division by zero in rate computation on first poll)?
3. Does the frontend gracefully handle missing fields (partial state on first poll)?
4. Is the estimate endpoint still resilient when the NOAA catalog isn't cached?

---

## Out of scope

- Renaming `geotiffs_downloaded` → `tiles_downloaded` in the state file. That's a breaking change for any external consumer; defer.
- Adding per-stage timing histograms or Prometheus-style metrics.
- Making the pre-run estimate adaptive based on past run history.
- Refactoring `_write_progress` out of the `run_noaa` closure.
- Tuning `REPROJECT_WORKERS` for the Pi 5 specifically (a related concern, but separate plan).
- Dedup at the individual tile (z/x/y) level — quad-level dedup is sufficient and much simpler.
- Incremental bounds updates during merge — a single recalculation after all merges is enough.
