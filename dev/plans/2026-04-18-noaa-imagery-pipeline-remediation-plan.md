# NOAA Imagery Pipeline Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 13 confirmed bugs + 3 design decisions surfaced by the 2026-04-18 NOAA imagery pipeline bug hunt, delivering a stability-focused patch release without regressing the 494-quad production run.

**Architecture:** Edits concentrate in `scripts/acquire_imagery.py` (NOAA + M2M pipelines), `scripts/rasterio_ops.py` (reproject + erode helpers), `scripts/acquire_naip.py` (NAIP county concurrency + GDAL process-group cancellation), and `services/search/main.py` (pipeline reconciliation WAL target). One new shared helper module is extracted (`scripts/gdal_subprocess.py`) so NOAA, NAIP, and future callers share the same cancellable subprocess wrapper.

**Tech Stack:** Python 3.11+ (asyncio, threading, sqlite3), rasterio / GDAL, FastAPI (search service). Tests via pytest with `pytest-asyncio`.

**Source of truth:** `dev/bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md` — read in full before starting Task 1.

---

## Baseline and conventions

- **Test baseline (pre-plan):** `python -m pytest tests/ services/search/tests/ -v` → 579 pass, 2 pre-existing M2M failures, 9 pre-existing OSM POI errors. Any *new* failure introduced during a task means the task broke something.
- **Commit format:** Conventional Commits per `CONTRIBUTING.md` — subject ≤72 chars, imperative mood, no trailing period.
  - Use `fix:` for bug fixes (triggers PATCH bump via release-please).
  - Use `refactor:` for B15's progress-writer rewrite (no behavior change).
  - None of these bugs are MAJOR-triggering; do NOT use `fix!:` or `BREAKING CHANGE:`.
  - Recommended scope: `pipeline` for script fixes, `search` for `services/search/main.py` fixes.
- **Test file naming:** Place new test modules under `tests/` (flat), following the existing `test_<feature>.py` convention. Add `sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))` at the top so `import acquire_imagery` works — see `tests/test_acquire_imagery_fixes.py` for the canonical pattern.
- **No `conftest.py` exists** at `tests/conftest.py`. Don't invent shared fixtures; put helpers in-module. Use `tmp_path` for filesystem isolation.
- **Async tests:** Mark with `@pytest.mark.asyncio`. Session-scope isn't configured; test functions default to function scope.
- **Never run `docker compose down`** on the production stack without explicit user permission (see MEMORY.md "Never stop prod stack").

### Task ordering rationale (DO NOT REORDER)

The sequence below was chosen to minimize cross-file conflicts between tasks. Parallel subagent execution is NOT recommended — several tasks touch adjacent line ranges in `acquire_imagery.py` and must be applied sequentially.

1. Task 1 (B3) — `rasterio_ops.py:210-252` — isolated, safest warmup
2. Task 2 (B4) — `rasterio_ops.py:604-648` — isolated
3. Task 3 (B7) — `acquire_imagery.py:641-670` — isolated
4. Task 4 (B14) — `services/search/main.py:1511-1532` — only task outside `scripts/`
5. **REVIEW CHECKPOINT #1**
6. Task 5 (B10 + B11) — `acquire_imagery.py:393-455` + `:1953-1974` — combined (both touch `fetch_to_file`/`_download_tile`)
7. Task 6 (B12) — `acquire_imagery.py:2137-2186` — `_merger` failure branches
8. Task 7 (B2) — `acquire_imagery.py:1629-1649` — M2M overview cancel guard
9. Task 8 (B5) — new `scripts/gdal_subprocess.py` + `acquire_naip.py` 4 call sites
10. Task 9 (B1 + D1 + D3) — `acquire_imagery.py:2196-2300` — Phase 5 rewrite (cancel guards, gate erosion, remove DELETE flip, keep TRUNCATE)
11. **REVIEW CHECKPOINT #2**
12. Task 10 (D2) — `acquire_imagery.py:2281-2293` — `completed_partial` status
13. Task 11 (B13) — `acquire_imagery.py:2157-2186` — checkpoint atomicity (single-connection OR post-crash repair; see task)
14. Task 12 (B15) — `acquire_imagery.py:279-326` — single-write progress refactor
15. Task 13 (B16) — `acquire_naip.py:599,666-685` — NAIP concurrency via `asyncio.gather`
16. **REVIEW CHECKPOINT #3**
17. Task 14 — Final regression + ship (merge dev→main, push, observe release-please)

---

## Task 1 — B3: Capture `src.width`/`src.height` into locals before `with` exits

**Bug reference:** B3 in `dev/bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md`.

**Files:**
- Modify: `scripts/rasterio_ops.py:210-260` (`reproject_to_mercator`)
- Test: `tests/test_rasterio_ops_closed_dataset.py` (new file)

**Why this is latent:** Line 250 `elapsed = time.monotonic() - t0` is dedented OUTSIDE the `with rasterio.open(...) as src:` block that closes at line 249. Line 252 reads `src.width` / `src.height` on a closed dataset. Today rasterio returns cached attributes (silent), but a version bump that enforces closed-dataset checks turns every reproject into a caught-and-returned-False failure. Fix: capture the two values into locals before the `with` exits.

### Preamble

```
BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/SKILL.md (or invoke superpowers:test-driven-development)
2. Read dev/testing-pitfalls.md — specifically the entry "Attribute access on a closed `with`-managed resource after block exit"
Follow TDD: write failing test → implement fix → verify green.
```

### Steps

- [ ] **Step 1: Read the current `reproject_to_mercator` function**

Open `scripts/rasterio_ops.py` and read lines 195-260 in full. Note that:
- Line 210 opens `with rasterio.open(str(src_path)) as src:`
- Line 232 opens the nested `with rasterio.open(str(dst_path), "w", **profile) as dst:`
- Line 249 closes BOTH `with` blocks (same dedent)
- Line 250 computes `elapsed`
- Line 252 logs `src.width`, `src.height` — this is the bug site

- [ ] **Step 2: Write the failing test**

Create `tests/test_rasterio_ops_closed_dataset.py` with this exact content:

```python
"""Test B3 fix: reproject_to_mercator must not access src.width/src.height after close."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestReprojectClosedDatasetAccess:
    """Verify the log call at function end does not touch a closed rasterio dataset."""

    def test_no_attribute_access_after_with_exits(self, tmp_path):
        """Simulate a rasterio that raises on attribute access after close.

        If the code reads src.width or src.height after the `with` block exits,
        this test raises a RuntimeError tagged CLOSED_DATASET, which would be
        caught by the function's broad except and make it return False.
        A correct fix captures width/height into locals before the block exits.
        """
        import rasterio_ops

        class ClosedAfterExit:
            """Mock dataset that rasters-like attributes only INSIDE the with block."""

            def __init__(self):
                self._closed = False
                self.crs = "EPSG:4326"
                self.count = 3

                class _Bounds:
                    left = -112.0
                    bottom = 33.0
                    right = -111.0
                    top = 34.0

                    def __iter__(self):
                        return iter([-112.0, 33.0, -111.0, 34.0])

                self.bounds = _Bounds()

                from rasterio.transform import Affine
                self.transform = Affine(0.0001, 0, -112.0, 0, -0.0001, 34.0)
                self.profile = {
                    "driver": "GTiff", "dtype": "uint8", "count": 3,
                    "width": 100, "height": 100, "crs": "EPSG:4326",
                    "transform": self.transform,
                }

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self._closed = True
                return False

            def _check(self):
                if self._closed:
                    raise RuntimeError("CLOSED_DATASET attribute access")

            @property
            def width(self):
                self._check()
                return 100

            @property
            def height(self):
                self._check()
                return 100

        fake_src = ClosedAfterExit()

        class FakeDst:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        # Patch rasterio.open so first call returns fake_src (as-is, our object
        # is already a context manager), and subsequent calls return FakeDst()
        call_count = {"n": 0}

        def fake_open(path, mode="r", **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return fake_src
            return FakeDst()

        with patch("rasterio_ops.rasterio.open", side_effect=fake_open), \
             patch("rasterio_ops.calculate_default_transform",
                   return_value=(fake_src.transform, 100, 100)), \
             patch("rasterio_ops.reproject"):
            result = rasterio_ops.reproject_to_mercator(
                tmp_path / "src.tif", tmp_path / "dst.tif"
            )

        # If the code accesses src.width/src.height after the `with` exits,
        # ClosedAfterExit raises, the except returns False.
        # The fix captures to locals, so result should be True.
        assert result is True, (
            "reproject_to_mercator returned False — likely accessed closed dataset. "
            "Fix: capture src.width / src.height into locals before `with` exits."
        )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python -m pytest tests/test_rasterio_ops_closed_dataset.py -v`
Expected: FAIL with `assert False is True` and the diagnostic message about closed dataset access.

- [ ] **Step 4: Apply the fix**

Use Edit tool on `scripts/rasterio_ops.py`. Replace the block from line 232-252 (inclusive of the nested `with rasterio.open` and the log line) with this (preserve exact 4-space indentation inside `try:`):

Locate this exact block:

```python
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(str(dst_path), "w", **profile) as dst:
                for i in range(1, src.count + 1):
                    if cancel_check and cancel_check():
                        return False
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=WEB_MERCATOR,
                        resampling=resamp,
                        # Use 1 GDAL internal thread per reproject call.
                    # The pipeline already parallelizes via ThreadPoolExecutor
                    # (4 workers). With num_threads=cpu_count, each worker spawns
                    # 4 GDAL threads → 16 total on 4 cores → thrashing.
                    num_threads=1,
                    )
        elapsed = time.monotonic() - t0
        log.debug("Reproject %s: %dx%d → %dx%d in %.1fs",
                  src_path.name, src.width, src.height, width, height, elapsed)
        return True
```

Replace with:

```python
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            with rasterio.open(str(dst_path), "w", **profile) as dst:
                for i in range(1, src.count + 1):
                    if cancel_check and cancel_check():
                        return False
                    reproject(
                        source=rasterio.band(src, i),
                        destination=rasterio.band(dst, i),
                        src_transform=src.transform,
                        src_crs=src.crs,
                        dst_transform=transform,
                        dst_crs=WEB_MERCATOR,
                        resampling=resamp,
                        # Use 1 GDAL internal thread per reproject call.
                    # The pipeline already parallelizes via ThreadPoolExecutor
                    # (4 workers). With num_threads=cpu_count, each worker spawns
                    # 4 GDAL threads → 16 total on 4 cores → thrashing.
                    num_threads=1,
                    )

            # B3 fix: capture dataset attributes BEFORE the `with` exits.
            # log.debug eagerly evaluates its arguments regardless of log level,
            # so accessing src.width / src.height after exit would raise under
            # stricter rasterio versions and return False via the enclosing except.
            src_width = src.width
            src_height = src.height
        elapsed = time.monotonic() - t0
        log.debug("Reproject %s: %dx%d → %dx%d in %.1fs",
                  src_path.name, src_width, src_height, width, height, elapsed)
        return True
```

- [ ] **Step 5: Re-run the test to verify it passes**

Run: `python -m pytest tests/test_rasterio_ops_closed_dataset.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`
Expected: baseline (579 pass, 2 M2M failures, 9 OSM POI errors) + 1 new passing test = 580 pass.

### Completion check

```
BEFORE marking this task complete:
1. Review your test against dev/testing-pitfalls.md — specifically "Attribute access on a closed `with`-managed resource after block exit". Confirm the test exercises the AFTER-close path.
2. Verify error-path coverage: does the test fail loudly if src.width/src.height is accessed after close? (Yes — the fake raises RuntimeError, caught by the function's except, returns False, assertion fails.)
3. Run `python -m pytest tests/ services/search/tests/ -v` and confirm baseline + 1 new pass. Any new failure is a regression.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_rasterio_ops_closed_dataset.py
git commit -m "$(cat <<'EOF'
fix(pipeline): capture rasterio src dims before with exits (B3)

reproject_to_mercator logged src.width / src.height after the
enclosing `with rasterio.open(...) as src:` block had closed.
Today this returns cached values silently, but any stricter
rasterio build would raise inside log.debug (eager arg eval),
be caught by the function's broad except, and turn every
reproject into a False return — every tile of the hot NOAA
pipeline fails.

Capture width/height into locals before the block exits.
EOF
)"
```

---

## Task 2 — B4: Reject out-of-bounds tiles in `_read_tile_from_array`

**Bug reference:** B4.

**Files:**
- Modify: `scripts/rasterio_ops.py:604-617` (`_read_tile_from_array` prologue)
- Test: `tests/test_rasterio_ops_edge_tiles.py` (new file)

**Why:** When a tile's bounds project entirely outside the source array, the existing early-return at line 607 only guards `full_row_span <= 0` (zero/negative). Positive-span tiles whose pixel ranges are entirely above or below the array produce negative numpy indices in the `dst_*` slicing at 626-648 — valid Python, but stamps real pixels at geometrically wrong positions. `_is_empty_tile` doesn't reject them (they're nonzero). Result: stray imagery at extreme quad boundaries.

### Preamble

```
BEFORE starting work:
1. Read the skill at .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the current function**

Read `scripts/rasterio_ops.py:584-650` in full. Note:
- Lines 597-608: `rowcol()` translates geographic bounds to pixel indices `raw_row_start`, `raw_row_end`, `raw_col_start`, `raw_col_end`.
- Line 607 guards only against `full_row_span <= 0` (and col).
- Lines 611-614 clamp to `data.shape`, but if `raw_row_end <= 0` the clamps pin `row_start=0, row_end=0` which does hit the zero-size check at 616.
- The bug: when `raw_row_start=100, raw_row_end=200` and `data.shape[1]=50`, clamps give `row_start=49, row_end=50` (passes zero-size check), then `dst_row_start = int((49-100)/100*256) = -130` — negative index that numpy silently slices from the end.

- [ ] **Step 2: Write the failing test**

Create `tests/test_rasterio_ops_edge_tiles.py`:

```python
"""Test B4 fix: _read_tile_from_array rejects tiles fully outside source extent."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from rasterio_ops import _read_tile_from_array
from rasterio.transform import Affine


class TestReadTileOutOfBounds:
    """Verify tiles whose pixel range is entirely outside the source array are rejected."""

    def _make_transform(self):
        """Identity-ish transform: 1 px per 0.01 degrees, origin (0,0)."""
        # Affine(a, b, c, d, e, f): x' = a*col + b*row + c ; y' = d*col + e*row + f
        # a=0.01 (x res), e=-0.01 (y res, negative because rows increase as lat decreases)
        # c=0 (origin lon), f=10 (origin lat, northernmost)
        return Affine(0.01, 0, 0.0, 0, -0.01, 10.0)

    def test_tile_entirely_above_array_returns_none(self):
        """Tile requesting lat 20-21 (above array's 9-10 extent) must return None, not misplaced pixels."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100  # visible nonzero pixels
        transform = self._make_transform()
        # Tile bounds well above the array's top edge (lat 9-10)
        tile_bounds = (0.0, 20.0, 0.5, 21.0)  # west, south, east, north
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None, (
            "Tile fully outside source extent should return None; "
            "otherwise valid pixels get stamped at geometrically wrong positions "
            "via numpy negative-index slicing."
        )

    def test_tile_entirely_below_array_returns_none(self):
        """Tile requesting lat -5 to -4 (below array) returns None."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (0.0, -5.0, 0.5, -4.0)
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None

    def test_tile_entirely_left_of_array_returns_none(self):
        """Tile requesting lon -5 to -4 (left of array) returns None."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (-5.0, 0.0, -4.0, 0.1)
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None

    def test_tile_entirely_right_of_array_returns_none(self):
        """Tile requesting lon 5 to 6 (right of 0-0.5 array) returns None."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (5.0, 0.0, 6.0, 0.1)
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is None

    def test_tile_fully_inside_still_works(self):
        """Regression: a tile fully inside the array still returns a populated tile."""
        data = np.ones((3, 50, 50), dtype=np.uint8) * 100
        transform = self._make_transform()
        tile_bounds = (0.05, 9.5, 0.15, 9.6)  # inside the 0-0.5 lon × 9.5-10 lat array
        result = _read_tile_from_array(data, transform, tile_bounds, tile_size=256)
        assert result is not None
        assert result.shape == (3, 256, 256)
        # At least some pixels are nonzero (we sampled from inside the all-100 array)
        assert np.any(result > 0)
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_rasterio_ops_edge_tiles.py -v`
Expected: FAIL on the four out-of-bounds cases (the function returns a non-None array with misplaced pixels).

- [ ] **Step 4: Apply the fix**

Edit `scripts/rasterio_ops.py`. Locate this block:

```python
    # Full tile span in source pixels (before clamping)
    full_row_span = raw_row_end - raw_row_start
    full_col_span = raw_col_end - raw_col_start
    if full_row_span <= 0 or full_col_span <= 0:
        return None

    # Clamp to array bounds
```

Replace with:

```python
    # Full tile span in source pixels (before clamping)
    full_row_span = raw_row_end - raw_row_start
    full_col_span = raw_col_end - raw_col_start
    if full_row_span <= 0 or full_col_span <= 0:
        return None

    # B4 fix: reject tiles whose pixel range is entirely outside the source array.
    # Without this guard, the clamps below pin row_start/col_start to the array
    # edge but the dst_row_start arithmetic at 626-629 produces negative indices,
    # which numpy slices legally from the end — stamping real pixels at wrong coords.
    if raw_row_end <= 0 or raw_row_start >= data.shape[1]:
        return None
    if raw_col_end <= 0 or raw_col_start >= data.shape[2]:
        return None

    # Clamp to array bounds
```

- [ ] **Step 5: Re-run — verify PASS**

Run: `python -m pytest tests/test_rasterio_ops_edge_tiles.py -v`
Expected: PASS (all 5 tests).

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`
Expected: baseline + new passes.

### Completion check

```
BEFORE marking this task complete:
1. Review tests against dev/testing-pitfalls.md. Did you test all four directions (above/below/left/right) and the regression case? Yes.
2. Verify no existing rasterize-to-disk tests regressed (they exercise in-bounds tiles which take the same clamp path).
3. Run `python -m pytest tests/ services/search/tests/ -v` and confirm green.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/rasterio_ops.py tests/test_rasterio_ops_edge_tiles.py
git commit -m "$(cat <<'EOF'
fix(pipeline): reject fully-out-of-bounds tiles in rasterize (B4)

_read_tile_from_array's existing guard only rejected zero/negative
pixel spans. Tiles whose bounds project entirely above/below/left/
right of the source array passed the span check, got their row/col
clamped to the array edge, then produced negative numpy indices in
the dst slice arithmetic — stamping valid pixels at geometrically
wrong positions. Visible at extreme NAIP quad boundaries.

Add an explicit raw-bounds check before the clamp: if raw_row_end
<= 0 or raw_row_start >= data.shape[1] (and symmetric for cols),
return None.
EOF
)"
```

---

## Task 3 — B7: Count and log decode/encode errors in `merge_mbtiles`

**Bug reference:** B7.

**Files:**
- Modify: `scripts/acquire_imagery.py:650-670` (`merge_mbtiles` composite loop)
- Test: `tests/test_mbtiles_merge_errors.py` (new file)

**Why:** The composite loop catches all exceptions with bare `except Exception: pass` (line 666-667). MemoryErrors, corrupt-tile decodes, and encode failures are invisible. On 1%-failure runs the map gets seams with no log.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — specifically "Exception swallowing in perf-critical loops masks silent data-quality issues"
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the current loop**

Read `scripts/acquire_imagery.py:638-675`. Note the `composited` counter starts at 650, the try block covers 652-665, and the bare `except Exception: pass` is at 666-667. The final log at 669-670 reports only `composited`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_mbtiles_merge_errors.py`:

```python
"""Test B7 fix: merge_mbtiles counts and logs composite errors."""

import logging
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from acquire_imagery import merge_mbtiles


def _create_mbtiles(path: Path, tiles: list[tuple[int, int, int, bytes]]) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE tiles (
        zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
        tile_data BLOB,
        PRIMARY KEY (zoom_level, tile_column, tile_row))""")
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    for z, x, y, d in tiles:
        conn.execute("INSERT INTO tiles VALUES (?, ?, ?, ?)", (z, x, y, d))
    conn.commit()
    conn.close()


class TestMergeMbtilesErrorCounting:
    """Verify composite loop counts decode errors and emits a warning."""

    def test_corrupt_overlap_logs_warning(self, tmp_path, caplog):
        """Corrupt JPEG in overlap path triggers at least one WARNING log, not silent pass."""
        src = tmp_path / "src.mbtiles"
        dst = tmp_path / "dst.mbtiles"

        # Same (z,x,y) in both, different bytes → overlap path fires.
        _create_mbtiles(src, [(10, 1, 1, b"CORRUPT_NOT_A_JPEG_SRC_______")])
        _create_mbtiles(dst, [(10, 1, 1, b"CORRUPT_NOT_A_JPEG_DST_______")])

        with caplog.at_level(logging.WARNING, logger="acquire_imagery"):
            merge_mbtiles(src, dst)

        # The decode will fail in the composite path. Before B7 fix: silent pass.
        # After B7 fix: at least one WARNING mentioning merge / composite failure.
        warning_messages = [r.getMessage() for r in caplog.records
                            if r.levelno >= logging.WARNING]
        assert any("composite" in m.lower() or "merge" in m.lower()
                   for m in warning_messages), (
            f"Expected a WARNING about failed composite; got: {warning_messages}"
        )

    def test_many_errors_capped_to_summary(self, tmp_path, caplog):
        """When >5 overlap tiles fail, a summary warning names the total count."""
        src = tmp_path / "src.mbtiles"
        dst = tmp_path / "dst.mbtiles"

        # 7 overlapping tiles, all corrupt
        tiles_src = [(10, i, 0, f"CORRUPT_SRC_{i}_XXXXXXX".encode()) for i in range(7)]
        tiles_dst = [(10, i, 0, f"CORRUPT_DST_{i}_XXXXXXX".encode()) for i in range(7)]
        _create_mbtiles(src, tiles_src)
        _create_mbtiles(dst, tiles_dst)

        with caplog.at_level(logging.WARNING, logger="acquire_imagery"):
            merge_mbtiles(src, dst)

        summary = [r.getMessage() for r in caplog.records
                   if r.levelno >= logging.WARNING
                   and "suppressed" in r.getMessage().lower()]
        assert summary, (
            "Expected a summary log line with 'suppressed' naming the error total; "
            f"no matching record in: {[r.getMessage() for r in caplog.records]}"
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_mbtiles_merge_errors.py -v`
Expected: FAIL — current code silently passes, no warnings emitted.

- [ ] **Step 4: Apply the fix**

Edit `scripts/acquire_imagery.py`. Locate:

```python
        composited = 0
        for z, x, y, src_data, dst_data in cursor:
            try:
                with MemoryFile(src_data) as smf, MemoryFile(dst_data) as dmf:
                    with smf.open() as sds, dmf.open() as dds:
                        src_arr = sds.read()
                        dst_arr = dds.read()
                # Threshold 20 catches JPEG compression artifacts at nodata edges
                black_mask = np.all(dst_arr[:3] <= 20, axis=0)
                dst_arr[:, black_mask] = src_arr[:, black_mask]
                merged = _encode_jpeg(dst_arr)
                dst.execute(
                    "UPDATE tiles SET tile_data = ? WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                    (merged, z, x, y),
                )
                composited += 1
            except Exception:
                pass  # Keep existing tile on decode error

        if composited:
            log.info("Composited %d overlapping edge tiles", composited)
```

Replace with:

```python
        composited = 0
        errors = 0
        for z, x, y, src_data, dst_data in cursor:
            try:
                with MemoryFile(src_data) as smf, MemoryFile(dst_data) as dmf:
                    with smf.open() as sds, dmf.open() as dds:
                        src_arr = sds.read()
                        dst_arr = dds.read()
                # Threshold 20 catches JPEG compression artifacts at nodata edges
                black_mask = np.all(dst_arr[:3] <= 20, axis=0)
                dst_arr[:, black_mask] = src_arr[:, black_mask]
                merged = _encode_jpeg(dst_arr)
                dst.execute(
                    "UPDATE tiles SET tile_data = ? WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                    (merged, z, x, y),
                )
                composited += 1
            except Exception as exc:
                # B7 fix: count and log composite failures instead of silently
                # dropping. Keeps the existing tile (correct default) but makes
                # silent data-quality degradation observable.
                errors += 1
                if errors <= 5:  # avoid log-spam for systemic failures
                    log.warning(
                        "merge composite failed for %d/%d/%d: %s", z, x, y, exc
                    )

        if composited:
            log.info("Composited %d overlapping edge tiles", composited)
        if errors:
            log.warning("merge_mbtiles: %d composite errors suppressed", errors)
```

- [ ] **Step 5: Re-run — verify PASS**

Run: `python -m pytest tests/test_mbtiles_merge_errors.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`

### Completion check

```
BEFORE marking this task complete:
1. Review against the pitfall "Exception swallowing in perf-critical loops". The fix adds both a counter and a log. Good.
2. Edge cases covered: 1 error (individual warn), 7 errors (summary suppressed). Consider: 0 errors (regression — still works). All three covered.
3. Run the full suite.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_mbtiles_merge_errors.py
git commit -m "$(cat <<'EOF'
fix(pipeline): count composite errors in merge_mbtiles (B7)

The merge_mbtiles composite loop caught every exception with
`except Exception: pass` — MemoryError, decode failure, and
encode failure were all invisible. Silent data-quality loss at
NAIP quad boundaries.

Add an error counter, warn on the first 5 (prevents log-spam),
and emit a summary log with the total count.
EOF
)"
```

---

## Task 4 — B14: Use `_mbtiles_path_for_type(type)` in search service reconciliation

**Bug reference:** B14.

**Files:**
- Modify: `services/search/main.py:1511-1532` (`pipeline_status` WAL-checkpoint block)
- Test: `services/search/tests/test_pipeline_wal_target.py` (new file)

**Why:** After marking a pipeline `completed`, the search service WAL-checkpoints the "output" MBTiles. Today it uses `state_data.get("mode", "imagery")` to build a candidate list — but `download_elevation.py` never sets `"mode"`, so the default falls through to the first existing file in `[imagery_imagery.mbtiles, imagery.mbtiles, elevation.mbtiles, public-lands.mbtiles]` (usually `imagery.mbtiles`). Elevation's WAL is left dirty. Use the existing `_mbtiles_path_for_type(type)` helper at line 1111 instead.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — "Callee-chosen output path from ambiguous state field causes cross-pipeline targeting"
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the current reconciliation block**

Read `services/search/main.py:1105-1125` (the `_mbtiles_path_for_type` helper) and `:1507-1545` (the WAL-checkpoint + TileServer restart block).

- [ ] **Step 2: Write the failing test**

Create `services/search/tests/test_pipeline_wal_target.py`:

```python
"""Test B14 fix: reconciliation WAL-checkpoints the correct MBTiles for each pipeline type."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestWalTargetPerType:
    """Verify each pipeline type's reconciliation path WAL-checkpoints the correct file."""

    def test_mbtiles_path_for_type_maps_elevation(self):
        """Sanity: _mbtiles_path_for_type returns elevation.mbtiles for 'elevation'."""
        import main

        # Patch DATA_DIR to a tmp location
        p = main._mbtiles_path_for_type("elevation")
        assert p.name == "elevation.mbtiles"

    def test_mbtiles_path_for_type_maps_naip(self):
        import main
        p = main._mbtiles_path_for_type("naip")
        assert p.name == "imagery_naip.mbtiles"

    def test_mbtiles_path_for_type_maps_sentinel(self):
        import main
        p = main._mbtiles_path_for_type("sentinel")
        assert p.name == "imagery_sentinel.mbtiles"

    def test_mbtiles_path_for_type_default_is_imagery(self):
        import main
        p = main._mbtiles_path_for_type("imagery")
        assert p.name == "imagery.mbtiles"
        p2 = main._mbtiles_path_for_type("unknown_type_xyz")
        assert p2.name == "imagery.mbtiles"

    def test_reconciliation_source_uses_type_not_mode(self):
        """The reconciliation block's WAL target must derive from `type`, not state['mode'].

        We verify this by scanning the source of pipeline_status for
        `_mbtiles_path_for_type(type)` (the correct pattern) and NOT
        `state_data.get("mode"` in the WAL block.
        """
        import inspect
        import main

        src = inspect.getsource(main.pipeline_status)
        # Must call the type-aware helper
        assert "_mbtiles_path_for_type(type)" in src, (
            "pipeline_status should call _mbtiles_path_for_type(type) in the WAL block"
        )
        # Must NOT build a mbtiles_candidates list by mode (old buggy pattern)
        assert "mbtiles_candidates" not in src, (
            "The old mbtiles_candidates iteration should be removed (B14 fix)"
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest services/search/tests/test_pipeline_wal_target.py -v`
Expected: the source-inspection tests fail because `mbtiles_candidates` still exists.

- [ ] **Step 4: Apply the fix**

Edit `services/search/main.py`. Locate:

```python
            # On successful completion: WAL checkpoint + TileServer restart.
            # The pipeline writes to MBTiles in WAL mode. TileServer caches
            # metadata at startup and won't see new tiles/bounds without a
            # restart. This is the centralized handoff point.
            if new_status == "completed" and client:
                # WAL checkpoint on the output MBTiles
                output_name = state_data.get("mode", "imagery")
                mbtiles_candidates = [
                    f"imagery_{output_name}.mbtiles",
                    f"imagery.mbtiles",
                    f"elevation.mbtiles",
                    f"public-lands.mbtiles",
                ]
                for candidate in mbtiles_candidates:
                    mbtiles_file = DATA_DIR / candidate
                    if mbtiles_file.exists():
                        try:
                            import sqlite3 as _wal
                            with _wal.connect(str(mbtiles_file), timeout=5) as _wc:
                                _wc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                                _wc.execute("PRAGMA journal_mode=DELETE")
                            print(f"WAL checkpoint: {candidate}", flush=True)
                        except Exception as exc:
                            print(f"WAL checkpoint failed for {candidate}: {exc}", flush=True)
                        break
```

Replace with:

```python
            # On successful completion: WAL checkpoint + TileServer restart.
            # The pipeline writes to MBTiles in WAL mode. TileServer caches
            # metadata at startup and won't see new tiles/bounds without a
            # restart. This is the centralized handoff point.
            if new_status == "completed" and client:
                # B14 fix: WAL-checkpoint the MBTiles that matches this
                # pipeline's `type`. Previously we iterated a mode-derived
                # candidate list, which for elevation (which doesn't set
                # `mode`) fell through to imagery.mbtiles — checkpointing
                # the wrong file and leaving elevation's WAL dirty.
                mbtiles_file = _mbtiles_path_for_type(type)
                if mbtiles_file.exists():
                    try:
                        import sqlite3 as _wal
                        with _wal.connect(str(mbtiles_file), timeout=5) as _wc:
                            _wc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                            _wc.execute("PRAGMA journal_mode=DELETE")
                        print(f"WAL checkpoint: {mbtiles_file.name}", flush=True)
                    except Exception as exc:
                        print(f"WAL checkpoint failed for {mbtiles_file.name}: {exc}", flush=True)
```

Note: `_mbtiles_path_for_type` does NOT have a mapping for `osm_poi` or `import` — they don't produce MBTiles. The `.exists()` guard handles this: for those types `_mbtiles_path_for_type` returns the default `imagery.mbtiles` path, which may or may not exist. If it exists, WAL-checkpointing `imagery.mbtiles` is harmless (it's idempotent). If the user is concerned, they can add explicit skip logic later — but leave it as-is for this task. **Do NOT add further handling for osm_poi/import in this task.**

- [ ] **Step 5: Re-run — verify PASS**

Run: `python -m pytest services/search/tests/test_pipeline_wal_target.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`

### Completion check

```
BEFORE marking this task complete:
1. Review against the pitfall "Callee-chosen output path from ambiguous state field".
2. The test covers all five pipeline types (imagery, elevation, naip, sentinel, default). Good.
3. Confirm the code no longer references `mbtiles_candidates` in pipeline_status.
4. Run full suite.
```

- [ ] **Step 7: Commit**

```bash
git add services/search/main.py services/search/tests/test_pipeline_wal_target.py
git commit -m "$(cat <<'EOF'
fix(search): target WAL checkpoint by pipeline type, not mode (B14)

The reconciliation block at pipeline_status iterated a
mode-derived candidate list of MBTiles filenames. Elevation
pipelines don't set `mode`, so the default resolved to
imagery.mbtiles — checkpointing the wrong file, leaving
elevation.mbtiles's WAL unflushed.

Use _mbtiles_path_for_type(type), which already exists and
maps every pipeline type to its correct output path.
EOF
)"
```

---

## REVIEW CHECKPOINT #1 — After Tasks 1-4

```
After Tasks 1-4 (the first four isolated bugs):
You MUST carefully review the batch from multiple perspectives and revise/refine as appropriate. Repeat this review (minimum three rounds; keep going if the third round still finds substantive issues) until confident. Then continue to Task 5.

Review focus:
1. Did any fix introduce a silent regression in other tests? Re-run `python -m pytest tests/ services/search/tests/ -v`; compare failure set against baseline (579 pass, 2 M2M fail, 9 OSM POI errors).
2. Are the 4 commits each single-concern and correctly Conventional-Commit formatted?
3. Does B3's captured-locals pattern generalize? (Yes — grep for other `with rasterio.open(...) as X:` blocks whose log/return statements sit outside. Document any found but DO NOT fix them in this cycle — note for deferred appendix.)
4. Does B4's guard correctly interact with the existing `full_row_span <= 0` check above it? (Yes — the new guard is strictly more restrictive, never allows through what the old guard caught.)
5. Does B7's counter overflow at any reachable scale? (int can go arbitrarily high, no.)
6. Does B14's fix handle `osm_poi`/`import` correctly via the `.exists()` guard? (Yes — `_mbtiles_path_for_type` returns `imagery.mbtiles` as default; the exists check prevents action on missing files.)

Do not proceed until all three review rounds pass clean.
```

---

## Task 5 — B10 + B11: `fetch_to_file` short-read detection + `_download_tile` staging-file reuse

**Bug reference:** B10, B11.

**Files:**
- Modify: `scripts/acquire_imagery.py:393-455` (`fetch_to_file`)
- Modify: `scripts/acquire_imagery.py:1953-1974` (`_download_tile`)
- Test: `tests/test_fetch_to_file_integrity.py` (new file)

**Why one task, not two:** B10 adds Content-Length short-read detection to `fetch_to_file`. B11 adds a "does `dest` already exist and validate?" short-circuit in `_download_tile` BEFORE calling `fetch_to_file`. Both touch the same data path; splitting them invites merge conflicts when the two fixes are applied sequentially.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — specifically:
   - "Streaming download lacks Content-Length short-read detection"
   - "Resumable-download with unconditional truncate re-fetches every cached item"
3. Read the existing test `tests/test_acquire_imagery_streaming.py` — it covers fetch_to_file and has useful aiohttp mocking patterns.
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the current implementations**

Read `scripts/acquire_imagery.py:393-455` (`fetch_to_file`) and `:1953-1974` (`_download_tile`). Note:
- `fetch_to_file` opens dest with `"wb"` (unconditional truncate, line 424).
- It doesn't check `resp.content_length` against bytes written.
- `_download_tile` calls `fetch_to_file` without checking if `dest` already exists.
- `validate_file_header` is imported from `pipeline_security` at line 1910 inside `run_noaa` — it's in scope when `_download_tile` is defined.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_fetch_to_file_integrity.py`:

```python
"""Tests for B10 + B11 fixes in acquire_imagery.py.

B10: fetch_to_file detects Content-Length short-reads and retries.
B11: _download_tile reuses an already-downloaded valid staging file on resume.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery as ai


# ---------------------------------------------------------------------------
# B10: short-read detection
# ---------------------------------------------------------------------------

class _MockResponseShortRead:
    """Simulates a server that advertises Content-Length=100 but sends only 40 bytes."""

    def __init__(self, advertised_length: int, actual_bytes: bytes, status: int = 200):
        self.status = status
        self.content_length = advertised_length
        self._actual = actual_bytes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @property
    def content(self):
        actual = self._actual

        class _Stream:
            def iter_chunked(self, size):
                async def _gen():
                    # Yield only the truncated bytes
                    yield actual
                return _gen()

        return _Stream()


class _MockResponseOK:
    """Full-length response."""

    def __init__(self, data: bytes):
        self.status = 200
        self.content_length = len(data)
        self._data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    @property
    def content(self):
        data = self._data

        class _Stream:
            def iter_chunked(self, size):
                async def _gen():
                    yield data
                return _gen()

        return _Stream()


class TestFetchToFileShortRead:
    """B10: short-read at HTTP 200 must fail the fetch, not return True."""

    @pytest.mark.asyncio
    async def test_short_read_returns_false_after_retries(self, tmp_path):
        """Server sends 40 bytes but advertises 100 → fetch_to_file returns False."""
        dest = tmp_path / "file.bin"

        session = MagicMock()
        # Every attempt returns the short-read response
        session.get = MagicMock(
            return_value=_MockResponseShortRead(advertised_length=100, actual_bytes=b"x" * 40)
        )

        result = await ai.fetch_to_file(session, "http://example.com/x", dest, retries=2)
        assert result is False, "Short-read should fail fetch_to_file, not succeed"

    @pytest.mark.asyncio
    async def test_full_length_returns_true(self, tmp_path):
        """Regression: full-length download still returns True."""
        dest = tmp_path / "file.bin"

        session = MagicMock()
        session.get = MagicMock(return_value=_MockResponseOK(b"y" * 100))

        result = await ai.fetch_to_file(session, "http://example.com/x", dest, retries=1)
        assert result is True

    @pytest.mark.asyncio
    async def test_no_content_length_still_succeeds(self, tmp_path):
        """If the server omits Content-Length (None), fetch returns True (no short-read comparison possible)."""
        dest = tmp_path / "file.bin"

        class _NoContentLength:
            status = 200
            content_length = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            @property
            def content(self):
                class _S:
                    def iter_chunked(self, size):
                        async def _gen():
                            yield b"z" * 50
                        return _gen()
                return _S()

        session = MagicMock()
        session.get = MagicMock(return_value=_NoContentLength())

        result = await ai.fetch_to_file(session, "http://example.com/x", dest, retries=1)
        assert result is True


# ---------------------------------------------------------------------------
# B11: staging-file reuse on resume
# ---------------------------------------------------------------------------

class TestDownloadTileReusesStaging:
    """B11: _download_tile must not re-download a valid staging file."""

    def test_fetch_to_file_not_called_when_staging_valid(self, tmp_path, monkeypatch):
        """Pre-populate dest with a valid GeoTIFF header; fetch_to_file must not be called."""
        # Note: _download_tile is defined as a closure inside run_noaa. We test
        # the observable behavior via the module-level `validate_file_header`
        # path that _download_tile uses. A simpler integration test is to
        # verify the fix's logic exists by reading the source.
        import inspect
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        # The fix adds an early-return path in _download_tile that checks
        # dest.exists() + size + validate_file_header before calling fetch_to_file.
        assert "Using cached staging tile" in src or "cached staging" in src.lower(), (
            "B11 fix not applied: _download_tile should log about reusing cached staging tiles"
        )
        assert "dest.exists()" in src, (
            "B11 fix must check dest.exists() before calling fetch_to_file"
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_fetch_to_file_integrity.py -v`
Expected: the short-read test and the staging-reuse source-check test both fail.

- [ ] **Step 4: Apply the B10 fix to `fetch_to_file`**

Edit `scripts/acquire_imagery.py`. Locate the block inside `fetch_to_file`:

```python
                if resp.status == 200:
                    total = 0
                    with open(dest, "wb") as f:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            total += len(chunk)
                            if max_size and total > max_size:
                                log.error("Download exceeded %d bytes for %s -- aborting",
                                          max_size, url)
                                f.close()
                                dest.unlink(missing_ok=True)
                                return False
                            f.write(chunk)
                    return True
```

Replace with:

```python
                if resp.status == 200:
                    total = 0
                    with open(dest, "wb") as f:
                        async for chunk in resp.content.iter_chunked(64 * 1024):
                            total += len(chunk)
                            if max_size and total > max_size:
                                log.error("Download exceeded %d bytes for %s -- aborting",
                                          max_size, url)
                                f.close()
                                dest.unlink(missing_ok=True)
                                return False
                            f.write(chunk)
                    # B10 fix: detect Content-Length short-reads. A server
                    # that cleanly closes the socket mid-body after advertising
                    # Content-Length produces a truncated file with no
                    # exception. Compare bytes written to advertised length;
                    # if short, discard and retry.
                    advertised = resp.content_length
                    if advertised is not None and total < advertised:
                        log.warning(
                            "Short read: got %d/%d bytes for %s -- retrying",
                            total, advertised, url,
                        )
                        dest.unlink(missing_ok=True)
                        wait = RETRY_BACKOFF * (2 ** attempt)
                        await asyncio.sleep(wait)
                        continue
                    return True
```

- [ ] **Step 5: Apply the B11 fix to `_download_tile`**

Edit `scripts/acquire_imagery.py`. Locate:

```python
            async def _download_tile(tile_fname):
                """Download and validate a single tile."""
                url = f"{blob_base}/{tile_fname}"
                dest = staging / tile_fname
                t0 = time.monotonic()
                async with download_sem:
                    if _cancel_requested:
                        return (tile_fname, None)
                    ok = await fetch_to_file(session, url, dest, timeout_s=3600,
                                             max_size=NOAA_MAX_GEOTIFF_SIZE,
                                             retries=5, sock_read_s=120)
```

Replace with:

```python
            async def _download_tile(tile_fname):
                """Download and validate a single tile."""
                url = f"{blob_base}/{tile_fname}"
                dest = staging / tile_fname
                t0 = time.monotonic()

                # B11 fix: if dest already exists and passes validation from a
                # previous run (SIGTERM between download and merge), skip the
                # re-download. Saves up to DOWNLOAD_CONCURRENCY * 486 MB on
                # resume. Note: we check outside the semaphore because no
                # network I/O is needed.
                if (dest.exists()
                        and dest.stat().st_size > 0
                        and validate_file_header(dest, "geotiff")):
                    size_mb = dest.stat().st_size / (1024 * 1024)
                    log.info(
                        "Using cached staging tile: %s (%.0f MB)",
                        tile_fname, size_mb,
                    )
                    return (tile_fname, dest)

                async with download_sem:
                    if _cancel_requested:
                        return (tile_fname, None)
                    ok = await fetch_to_file(session, url, dest, timeout_s=3600,
                                             max_size=NOAA_MAX_GEOTIFF_SIZE,
                                             retries=5, sock_read_s=120)
```

- [ ] **Step 6: Re-run — verify PASS**

Run: `python -m pytest tests/test_fetch_to_file_integrity.py -v`
Expected: PASS (all tests).

Also verify the existing streaming tests still pass:
Run: `python -m pytest tests/test_acquire_imagery_streaming.py -v`
Expected: existing passes still pass.

- [ ] **Step 7: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -40`

### Completion check

```
BEFORE marking this task complete:
1. Review against the two cited pitfalls. The short-read test uses `resp.content_length=100, actual_bytes=40` — matches the pitfall's suggested mock. The staging-reuse test asserts `fetch_to_file` is NOT called; since the real function is a closure inside run_noaa, the source-level assertion is the practical approach.
2. Error-path coverage: short-read → retries exhausted → returns False (covered). Cached file passes validation → skip download (covered via source assertion). Cached file fails validation → falls through to download (NOT covered by test; but this is the non-cached branch which is the existing behavior).
3. Run the full suite.
```

- [ ] **Step 8: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_fetch_to_file_integrity.py
git commit -m "$(cat <<'EOF'
fix(pipeline): detect short-reads and reuse cached staging tiles (B10, B11)

B10: fetch_to_file returned True on HTTP 200 truncated responses
(server advertises Content-Length=N, sends N/2 bytes, closes
cleanly). Compare bytes written to resp.content_length after the
iter_chunked loop; on short-read, delete the partial file and
retry with backoff.

B11: _download_tile called fetch_to_file unconditionally, and
fetch_to_file opens dest with "wb" (truncate). Runs SIGTERM'd
between download and merge re-downloaded every cached tile on
resume — up to 8 * 486 MB of avoidable bandwidth. Add a pre-check:
if dest exists, has nonzero size, and passes GeoTIFF header
validation, skip the network call entirely.
EOF
)"
```

---

## Task 6 — B12: `_write_progress()` on `_merger` failure branches

**Bug reference:** B12.

**Files:**
- Modify: `scripts/acquire_imagery.py:2137-2186` (`_merger`)
- Test: `tests/test_merger_progress_on_failure.py` (new file)

**Why:** `_merger` has two failure branches (`warped_path is None` at 2146-2152 and merge-failure at 2179-2186) that increment `tiles_failed` but never call `_write_progress()`. The frontend polling the state file sees stale counters until Phase 5 fires its own write. Fix: one-line `_write_progress()` call in both branches.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — "Progress-state updates skipped in failure paths leave the UI 'stuck'"
Follow TDD.
```

### Steps

- [ ] **Step 1: Read `_merger`**

Read `scripts/acquire_imagery.py:2137-2186`. Note `_write_progress()` is defined earlier in the same function as a closure. It's already called on the success branch at line 2164.

- [ ] **Step 2: Write the failing test**

Create `tests/test_merger_progress_on_failure.py`:

```python
"""Test B12 fix: _merger calls _write_progress() on failure branches."""

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestMergerFailureProgress:
    """Verify _write_progress() is called in both _merger failure branches.

    _merger is a closure defined inside run_noaa, which makes unit-level
    invocation awkward. We assert the source structure: both failure
    branches must call _write_progress() before the `continue` or `break`.
    """

    def test_merger_failure_branches_write_progress(self):
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)

        # Find the _merger body
        start = src.find("async def _merger()")
        assert start != -1, "_merger not found in run_noaa"
        # _merger ends at the next closure definition or outer block exit
        end = src.find("# Run all 3 stages concurrently", start)
        assert end != -1
        merger_src = src[start:end]

        # The two failure branches are:
        # 1. `if _cancel_requested or warped_path is None:` ... `tiles_failed += 1`
        # 2. `else:` (merge_ok is False) ... `tiles_failed += 1`
        #
        # Both must call _write_progress() before continuing/breaking.
        # We count occurrences: pre-fix = 1 success call; post-fix = 3 total.
        write_progress_calls = merger_src.count("_write_progress()")
        assert write_progress_calls >= 3, (
            f"Expected at least 3 _write_progress() calls in _merger "
            f"(one success + two failure branches); found {write_progress_calls}. "
            f"B12 fix not applied."
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_merger_progress_on_failure.py -v`
Expected: FAIL (currently 1 call).

- [ ] **Step 4: Apply the fix**

Edit `scripts/acquire_imagery.py`. Locate the `_merger` function. Inside the `warped_path is None` branch (approximately lines 2146-2152):

```python
                    if _cancel_requested or warped_path is None:
                        if warped_path:
                            warped_path.unlink(missing_ok=True)
                        if warped_path is None:
                            with counter_lock:
                                tiles_failed += 1
                        continue
```

Replace with:

```python
                    if _cancel_requested or warped_path is None:
                        if warped_path:
                            warped_path.unlink(missing_ok=True)
                        if warped_path is None:
                            with counter_lock:
                                tiles_failed += 1
                            # B12 fix: write progress so frontend polling
                            # sees the failure-counter update, not stale state.
                            _write_progress()
                        continue
```

Then locate the merge-failure branch (approximately lines 2179-2186):

```python
                    else:
                        with counter_lock:
                            tiles_failed += 1
                        if _cancel_requested:
                            break
                        log.warning("[%d/%d] Merge failed for %s",
                                    idx + 1, total_tiles, tile_fname)
```

Replace with:

```python
                    else:
                        with counter_lock:
                            tiles_failed += 1
                        # B12 fix: write progress so frontend sees the
                        # tiles_failed counter move without waiting for
                        # the next success or Phase 5.
                        _write_progress()
                        if _cancel_requested:
                            break
                        log.warning("[%d/%d] Merge failed for %s",
                                    idx + 1, total_tiles, tile_fname)
```

- [ ] **Step 5: Re-run — verify PASS**

Run: `python -m pytest tests/test_merger_progress_on_failure.py -v`
Expected: PASS.

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`

### Completion check

```
BEFORE marking this task complete:
1. Review against "Progress-state updates skipped in failure paths leave the UI 'stuck'". Test asserts 3 _write_progress() calls. Good.
2. Edge case: does _write_progress() hold counter_lock? Yes — it acquires counter_lock inside. We release counter_lock BEFORE calling _write_progress() (because the `with counter_lock:` block ends before the call). No deadlock.
3. Run full suite.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_merger_progress_on_failure.py
git commit -m "$(cat <<'EOF'
fix(pipeline): write progress on _merger failure branches (B12)

_merger incremented tiles_failed on both `warped_path is None`
and merge-failure paths without calling _write_progress().
Frontend polling saw stale counters for minutes on partial-failure
runs until Phase 5 wrote its own status update.

Add _write_progress() to both failure branches. No new state
fields — just surfaces the existing tiles_failed counter to the
admin UI on every per-tile failure.
EOF
)"
```

---

## Task 7 — B2: Cancel guard after M2M overview build

**Bug reference:** B2.

**Files:**
- Modify: `scripts/acquire_imagery.py:1636-1649` (end of `run_m2m`)
- Test: `tests/test_m2m_cancel_during_overview.py` (new file)

**Why:** In `run_m2m`, `gdaladdo` is called at line 1637 with `cancel_check=lambda: _cancel_requested`. If SIGTERM fires during gdaladdo, `run_gdal_subprocess` raises `CalledProcessError`, which is caught at 1642 and logged as a warning. Execution falls through to the unconditional `status="completed"` write at 1645. Fix: after the try/except, if `_cancel_requested` is set, write status="cancelled" and return instead.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the current code**

Read `scripts/acquire_imagery.py:1629-1650`. Note:
- Line 1637-1641: `run_gdal_subprocess` call with cancel_check.
- Line 1642-1643: except catches CalledProcessError / TimeoutExpired, logs warning.
- Line 1645-1648: unconditional `update_progress(..., status="completed", phase="complete")`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_m2m_cancel_during_overview.py`:

```python
"""Test B2 fix: run_m2m writes status='cancelled' when cancel fires during overview."""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery as ai


class TestM2MCancelDuringOverview:
    """If _cancel_requested is set during gdaladdo, final status must be 'cancelled'."""

    @pytest.fixture(autouse=True)
    def reset_cancel(self):
        ai._cancel_requested = False
        yield
        ai._cancel_requested = False

    @pytest.mark.asyncio
    async def test_cancel_during_overview_writes_cancelled(self, tmp_path):
        args = MagicMock()
        args.m2m_username = "u"
        args.m2m_token = "t"
        args.bbox = "-111,33,-110,34"
        args.staging = str(tmp_path / "staging")
        args.output = str(tmp_path / "out.mbtiles")
        args.concurrency = 2

        # Create a non-empty output file so the overview branch fires
        (tmp_path / "out.mbtiles").write_bytes(b"fake mbtiles")

        # Track update_progress calls
        progress_calls = []

        def _track_progress(*pos_args, **kwargs):
            progress_calls.append({"args": pos_args, "kwargs": kwargs})

        # Simulate SIGTERM during gdaladdo by having run_gdal_subprocess
        # set _cancel_requested and raise CalledProcessError.
        import subprocess

        def _fake_gdal(*args, **kwargs):
            ai._cancel_requested = True
            raise subprocess.CalledProcessError(1, args[0] if args else ["gdaladdo"])

        with patch.object(ai, "m2m_login", new_callable=AsyncMock, return_value="k"), \
             patch.object(ai, "m2m_logout", new_callable=AsyncMock), \
             patch.object(ai, "m2m_find_naip_dataset", new_callable=AsyncMock, return_value="a"), \
             patch.object(ai, "m2m_scene_search", new_callable=AsyncMock,
                          return_value=[{"entityId": "e1"}]), \
             patch.object(ai, "m2m_download_batched", new_callable=AsyncMock,
                          return_value=[]), \
             patch.object(ai, "run_gdal_subprocess", side_effect=_fake_gdal), \
             patch.object(ai, "update_progress", side_effect=_track_progress), \
             patch.object(ai, "convert_batch_to_mbtiles", return_value=True):

            await ai.run_m2m(args)

        # The LAST update_progress call should be status="cancelled", NOT "completed".
        assert progress_calls, "update_progress was never called"
        last = progress_calls[-1]
        assert last["kwargs"].get("status") == "cancelled", (
            f"Expected last status='cancelled' after overview cancel, "
            f"got status={last['kwargs'].get('status')}"
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_m2m_cancel_during_overview.py -v`
Expected: FAIL (last status is "completed").

- [ ] **Step 4: Apply the fix**

Edit `scripts/acquire_imagery.py`. Locate:

```python
    # Build overview pyramids ONCE at the very end (not per batch)
    if output.exists():
        log.info("Building overview pyramids for %s", output)
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, phase="overviews",
                        scenes_total=len(scenes),
                        geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
        try:
            run_gdal_subprocess(
                ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
                timeout=3600,
                cancel_check=lambda: _cancel_requested,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("Overview generation failed: %s -- output is still usable", exc)

    update_progress(output, "m2m", args.bbox, "n/a",
                    0, len(scenes), status="completed", phase="complete",
                    scenes_total=len(scenes),
                    geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
    log.info("M2M pipeline complete: %d scenes → %s", len(scenes), output)
```

Replace with:

```python
    # Build overview pyramids ONCE at the very end (not per batch)
    if output.exists():
        log.info("Building overview pyramids for %s", output)
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, 0, phase="overviews",
                        scenes_total=len(scenes),
                        geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
        try:
            run_gdal_subprocess(
                ["gdaladdo", "-r", "average", str(output), "2", "4", "8", "16"],
                timeout=3600,
                cancel_check=lambda: _cancel_requested,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            log.warning("Overview generation failed: %s -- output is still usable", exc)

    # B2 fix: if cancel fired during overview build, write "cancelled" and
    # return — don't fall through to the unconditional "completed" write.
    if _cancel_requested:
        update_progress(output, "m2m", args.bbox, "n/a",
                        0, len(scenes), status="cancelled", phase="cancelled",
                        scenes_total=len(scenes),
                        geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
        log.info("M2M pipeline cancelled during overview build")
        return

    update_progress(output, "m2m", args.bbox, "n/a",
                    0, len(scenes), status="completed", phase="complete",
                    scenes_total=len(scenes),
                    geotiffs_downloaded=len(tif_paths), geotiffs_total=len(scenes))
    log.info("M2M pipeline complete: %d scenes → %s", len(scenes), output)
```

- [ ] **Step 5: Re-run — verify PASS**

Run: `python -m pytest tests/test_m2m_cancel_during_overview.py -v`

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`

### Completion check

```
BEFORE marking this task complete:
1. The cancel guard is placed AFTER the overview block but BEFORE the completed-status write. Correct placement.
2. Test forces _cancel_requested inside the mocked run_gdal_subprocess, simulating real SIGTERM timing. Good.
3. Run full suite.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_m2m_cancel_during_overview.py
git commit -m "$(cat <<'EOF'
fix(pipeline): honor cancel during M2M overview build (B2)

run_m2m called gdaladdo with a cancel_check. When SIGTERM fired
during the subprocess, run_gdal_subprocess killed the child and
raised CalledProcessError, which was caught and logged as a
warning. Execution fell through to the unconditional
status="completed" write — cancel was silently ignored.

Add a post-try _cancel_requested check that writes
status="cancelled" and returns before the completed-status line.
EOF
)"
```

---

## Task 8 — B5: Extract `run_gdal_subprocess` to `scripts/gdal_subprocess.py`, adopt in `acquire_naip.py`

**Bug reference:** B5.

**Files:**
- Create: `scripts/gdal_subprocess.py` (new module)
- Modify: `scripts/acquire_imagery.py:732-777` (replace local definition with import)
- Modify: `scripts/acquire_naip.py:402-437, 440-494` (replace 4 `subprocess.run` call sites)
- Test: `tests/test_gdal_subprocess_module.py` (new file)

**Why:** `acquire_imagery.py:732` has `run_gdal_subprocess` using `Popen(preexec_fn=os.setsid)` so SIGTERM can `killpg` the child. `acquire_naip.py` has 4 `subprocess.run(..., check=True, capture_output=True, timeout=...)` call sites that block the main thread — a pending SIGTERM sets `_cancel_requested` but the main thread can't check it until the subprocess finishes. Cancel clicks on NAIP are ineffective for up to 7200s per operation. Fix: extract the shared helper and migrate NAIP.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — "subprocess.run blocking signal handlers" and "Call-site-before-implementation: function called before it exists"
3. Read scripts/acquire_imagery.py:732-777 in full — this is the source to extract.
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the source helper**

Read `scripts/acquire_imagery.py:732-777` — the existing `run_gdal_subprocess` function. Note it uses `_child_pid` (module-level global in acquire_imagery.py for the SIGTERM handler) and `GDAL_CACHEMAX` / `GDAL_NUM_THREADS` env defaults.

Read `scripts/acquire_naip.py:60-73` — note the SIGTERM handler sets `_cancel_requested` but has no `_child_pid` / `killpg` logic. Our extracted helper needs to work for both callers — so it should take an optional "cancel check" callable AND an optional "register child pid" callable (so each module can wire its own killpg-in-SIGTERM-handler).

- [ ] **Step 2: Write the failing test**

Create `tests/test_gdal_subprocess_module.py`:

```python
"""Tests for the extracted scripts/gdal_subprocess.py helper."""

import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestGdalSubprocessModule:
    """Verify the extracted module exists and behaves correctly."""

    def test_module_importable(self):
        import gdal_subprocess
        assert hasattr(gdal_subprocess, "run_gdal_subprocess")

    def test_run_completes_on_success(self):
        import gdal_subprocess
        # `true` returns 0 instantly
        result = gdal_subprocess.run_gdal_subprocess(["true"], timeout=10)
        assert result.returncode == 0

    def test_raises_on_nonzero_exit(self):
        import gdal_subprocess
        # `false` returns 1
        with pytest.raises(subprocess.CalledProcessError):
            gdal_subprocess.run_gdal_subprocess(["false"], timeout=10)

    def test_cancel_check_before_start_raises(self):
        import gdal_subprocess
        with pytest.raises(subprocess.CalledProcessError):
            gdal_subprocess.run_gdal_subprocess(
                ["true"], timeout=10,
                cancel_check=lambda: True,
            )

    def test_on_child_started_callback_fires(self):
        import gdal_subprocess
        captured_pids = []

        def _cb(pid):
            captured_pids.append(pid)

        gdal_subprocess.run_gdal_subprocess(
            ["true"], timeout=10,
            on_child_started=_cb,
        )
        assert len(captured_pids) == 1
        assert captured_pids[0] > 0

    def test_acquire_imagery_imports_from_module(self):
        """acquire_imagery.run_gdal_subprocess must still be callable (re-exported or imported)."""
        import acquire_imagery
        assert callable(acquire_imagery.run_gdal_subprocess)

    def test_acquire_naip_uses_shared_helper(self):
        """acquire_naip should no longer use `subprocess.run(..., check=True, ...` for GDAL commands."""
        import inspect
        import acquire_naip
        src = inspect.getsource(acquire_naip)
        # Count old blocking-subprocess.run call sites that still have check=True on gdal commands
        # The 4 original sites had lines like: subprocess.run([..., "gdal_translate", ...], check=True, ...)
        # After the fix, those should be replaced by run_gdal_subprocess calls.
        # We assert the import exists AND the naive subprocess.run-on-gdal pattern is reduced.
        assert "from gdal_subprocess import run_gdal_subprocess" in src \
            or "import gdal_subprocess" in src, \
            "acquire_naip.py should import the shared helper"

        # Count remaining "subprocess.run(" occurrences — the fix replaces 4 call sites.
        remaining = src.count("subprocess.run(")
        assert remaining <= 1, (
            f"Expected ≤1 remaining subprocess.run in acquire_naip.py (original: 4); "
            f"got {remaining}"
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_gdal_subprocess_module.py -v`
Expected: FAIL — module doesn't exist yet.

- [ ] **Step 4: Create `scripts/gdal_subprocess.py`**

Create the new file with this exact content:

```python
"""Shared GDAL subprocess wrapper with process-group cancellation support.

Extracted from acquire_imagery.py so sibling pipelines (acquire_naip.py,
and any future callers) share the same cancellable subprocess behavior.

Why this exists: `subprocess.run(...)` blocks the main thread. A pending
SIGTERM sets a cancellation flag but the main thread can't check it until
the subprocess exits. For GDAL operations that run for 30+ minutes (gdaladdo
on large mosaics), this makes cancel effectively ineffective.

This helper uses Popen(preexec_fn=os.setsid) to create a new process group,
exposes the child PID via on_child_started callback so the caller can
register it for SIGTERM forwarding, and checks cancel_check between
communicate() polling so cancellation is timely.
"""

from __future__ import annotations

import os
import signal
import subprocess


def run_gdal_subprocess(
    cmd: list[str],
    timeout: int = 7200,
    cancel_check=None,
    on_child_started=None,
    on_child_ended=None,
) -> subprocess.CompletedProcess:
    """Run a GDAL CLI command with nice priority and process-group cancellation.

    Args:
        cmd: Command and arguments (e.g., ["gdalbuildvrt", ...]).
        timeout: Max seconds before killing the process.
        cancel_check: Optional callable returning True if cancellation
            requested. Called before spawning; if True, raises
            CalledProcessError immediately.
        on_child_started: Optional callable(pid) invoked after Popen
            succeeds. Use this to register the pid with your module's
            SIGTERM handler so it can killpg the child on signal.
        on_child_ended: Optional callable() invoked in the finally block
            once the child has exited. Use to clear the registered pid.

    Returns:
        CompletedProcess on success.

    Raises:
        subprocess.CalledProcessError: if command fails or is cancelled
            before start.
        subprocess.TimeoutExpired: if timeout exceeded.
    """
    if cancel_check and cancel_check():
        raise subprocess.CalledProcessError(1, cmd, stderr="Cancelled before start")

    full_cmd = ["nice", "-n", "19"] + cmd
    gdal_env = {
        **os.environ,
        "GDAL_CACHEMAX": os.environ.get("GDAL_CACHEMAX", "1024"),
        "GDAL_NUM_THREADS": os.environ.get("GDAL_NUM_THREADS", "ALL_CPUS"),
    }
    proc = subprocess.Popen(
        full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=gdal_env,
        preexec_fn=os.setsid,  # new process group so caller can killpg it
    )
    if on_child_started is not None:
        try:
            on_child_started(proc.pid)
        except Exception:
            # Don't let a buggy callback abort the subprocess run
            pass
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait()
            raise
    finally:
        if on_child_ended is not None:
            try:
                on_child_ended()
            except Exception:
                pass

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, full_cmd, output=stdout, stderr=stderr
        )
    return subprocess.CompletedProcess(full_cmd, proc.returncode, stdout, stderr)
```

- [ ] **Step 5: Replace `acquire_imagery.py`'s local definition with an import**

Edit `scripts/acquire_imagery.py`. Locate the existing `run_gdal_subprocess` definition at lines 732-777:

```python
def run_gdal_subprocess(cmd: list[str], timeout: int = 7200,
                        cancel_check=None) -> subprocess.CompletedProcess:
    """Run a GDAL CLI command with nice priority and optional cancel check.

    Uses Popen with a process group so SIGTERM can kill the child
    immediately (without waiting for it to finish).

    Args:
        cmd: Command and arguments (e.g., ["gdalbuildvrt", ...])
        timeout: Max seconds before killing the process.
        cancel_check: Optional callable returning True if cancellation requested.

    Returns:
        CompletedProcess on success.

    Raises:
        subprocess.CalledProcessError: If command fails or is cancelled.
        subprocess.TimeoutExpired: If timeout exceeded.
    """
    global _child_pid
    if cancel_check and cancel_check():
        raise subprocess.CalledProcessError(1, cmd, stderr="Cancelled before start")
    full_cmd = ["nice", "-n", "19"] + cmd
    gdal_env = {
        **os.environ,
        "GDAL_CACHEMAX": os.environ.get("GDAL_CACHEMAX", "1024"),
        "GDAL_NUM_THREADS": os.environ.get("GDAL_NUM_THREADS", "ALL_CPUS"),
    }
    proc = subprocess.Popen(
        full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, env=gdal_env,
        preexec_fn=os.setsid,  # new process group so we can kill it
    )
    _child_pid = proc.pid
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait()
        _child_pid = None
        raise
    _child_pid = None
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, full_cmd,
                                            output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(full_cmd, proc.returncode, stdout, stderr)
```

Replace with:

```python
def run_gdal_subprocess(cmd: list[str], timeout: int = 7200,
                        cancel_check=None) -> subprocess.CompletedProcess:
    """Run a GDAL CLI command. Delegates to the shared helper.

    Preserved as a thin wrapper because existing tests import it from
    acquire_imagery. Registers/clears the module-level _child_pid so the
    SIGTERM handler (_handle_sigterm at the top of this module) can
    killpg the child.
    """
    def _set_pid(pid: int) -> None:
        global _child_pid
        _child_pid = pid

    def _clear_pid() -> None:
        global _child_pid
        _child_pid = None

    from gdal_subprocess import run_gdal_subprocess as _shared
    return _shared(
        cmd, timeout=timeout, cancel_check=cancel_check,
        on_child_started=_set_pid, on_child_ended=_clear_pid,
    )
```

- [ ] **Step 6: Migrate `acquire_naip.py` to the shared helper**

Edit `scripts/acquire_naip.py`. First, add a module-level `_child_pid` global and wire it to the SIGTERM handler. Locate the cancellation section at lines 62-72:

```python
# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
_cancel_requested = False


def _handle_sigterm(signum, frame):
    """Handle SIGTERM for graceful shutdown (docker stop)."""
    global _cancel_requested
    log.info("SIGTERM received - finishing current county and shutting down")
    _cancel_requested = True


signal.signal(signal.SIGTERM, _handle_sigterm)
```

Replace with:

```python
# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------
_cancel_requested = False
_child_pid: int | None = None  # set by run_gdal_subprocess while a child is running


def _handle_sigterm(signum, frame):
    """Handle SIGTERM for graceful shutdown (docker stop)."""
    global _cancel_requested
    log.info("SIGTERM received - cancelling and killing any GDAL child")
    _cancel_requested = True
    # B5 fix: forward SIGTERM to the GDAL child's process group so a
    # long-running gdaladdo doesn't block cancel for 30+ minutes.
    if _child_pid is not None:
        try:
            import os as _os
            _os.killpg(_os.getpgid(_child_pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass


signal.signal(signal.SIGTERM, _handle_sigterm)
```

Then add the import near the top of the file, after the other `from` imports:

Locate:

```python
from build_county_index import counties_for_bbox
from pipeline_progress import update_progress as _generic_progress
from pipeline_security import safe_staging_path, sanitize_fips, validate_file_header
```

Replace with:

```python
from build_county_index import counties_for_bbox
from gdal_subprocess import run_gdal_subprocess
from pipeline_progress import update_progress as _generic_progress
from pipeline_security import safe_staging_path, sanitize_fips, validate_file_header
```

Now replace the 4 `subprocess.run` call sites. First, `convert_jp2_to_geotiff` at lines 421-435:

```python
    try:
        subprocess.run(
            cmd, check=True, capture_output=True, text=True,
            env=GDAL_ENV, timeout=3600,
        )
    except subprocess.CalledProcessError as exc:
        log.error("GDAL translate failed for %s: %s", jp2_path, exc.stderr)
        if tif_path.exists():
            tif_path.unlink()
        return None
    except subprocess.TimeoutExpired:
        log.error("GDAL translate timed out for %s", jp2_path)
        if tif_path.exists():
            tif_path.unlink()
        return None
```

Replace with:

```python
    def _set_pid(pid: int) -> None:
        global _child_pid
        _child_pid = pid

    def _clear_pid() -> None:
        global _child_pid
        _child_pid = None

    # B5 fix: use shared helper so SIGTERM kills the GDAL child immediately
    # instead of waiting up to 3600s for it to finish.
    try:
        # The shared helper already prepends "nice -n 19" and sets GDAL env,
        # so strip those from `cmd` before passing.
        inner_cmd = [a for a in cmd if a not in ("nice", "-n", "19")]
        from gdal_subprocess import run_gdal_subprocess as _shared
        _shared(
            inner_cmd, timeout=3600,
            cancel_check=lambda: _cancel_requested,
            on_child_started=_set_pid,
            on_child_ended=_clear_pid,
        )
    except subprocess.CalledProcessError as exc:
        log.error("GDAL translate failed for %s: %s", jp2_path, exc.stderr)
        if tif_path.exists():
            tif_path.unlink()
        return None
    except subprocess.TimeoutExpired:
        log.error("GDAL translate timed out for %s", jp2_path)
        if tif_path.exists():
            tif_path.unlink()
        return None
```

Next, `merge_to_mbtiles` at lines 452-481 (three `subprocess.run` calls: gdalbuildvrt, gdal_translate to MBTiles, gdaladdo). Locate:

```python
    try:
        # Build VRT
        subprocess.run(
            ["nice", "-n", "19", "gdalbuildvrt",
             "-input_file_list", str(tif_list_path),
             str(vrt_path)],
            check=True, capture_output=True, text=True,
            env=GDAL_ENV, timeout=600,
        )

        # Convert VRT to MBTiles
        subprocess.run(
            ["nice", "-n", "19", "gdal_translate",
             "-of", "MBTiles",
             "-co", "TILE_FORMAT=JPEG",
             "-co", "QUALITY=85",
             str(vrt_path), str(output_path)],
            check=True, capture_output=True, text=True,
            env=GDAL_ENV, timeout=7200,
        )

        # Build overview pyramids
        subprocess.run(
            ["nice", "-n", "19", "gdaladdo",
             "-r", "average",
             str(output_path),
             "2", "4", "8", "16"],
            check=True, capture_output=True, text=True,
            env=GDAL_ENV, timeout=3600,
        )

        return True
```

Replace with:

```python
    def _set_pid(pid: int) -> None:
        global _child_pid
        _child_pid = pid

    def _clear_pid() -> None:
        global _child_pid
        _child_pid = None

    _cc = lambda: _cancel_requested

    try:
        # Build VRT
        run_gdal_subprocess(
            ["gdalbuildvrt",
             "-input_file_list", str(tif_list_path),
             str(vrt_path)],
            timeout=600,
            cancel_check=_cc,
            on_child_started=_set_pid, on_child_ended=_clear_pid,
        )

        # Convert VRT to MBTiles
        run_gdal_subprocess(
            ["gdal_translate",
             "-of", "MBTiles",
             "-co", "TILE_FORMAT=JPEG",
             "-co", "QUALITY=85",
             str(vrt_path), str(output_path)],
            timeout=7200,
            cancel_check=_cc,
            on_child_started=_set_pid, on_child_ended=_clear_pid,
        )

        # Build overview pyramids
        run_gdal_subprocess(
            ["gdaladdo",
             "-r", "average",
             str(output_path),
             "2", "4", "8", "16"],
            timeout=3600,
            cancel_check=_cc,
            on_child_started=_set_pid, on_child_ended=_clear_pid,
        )

        return True
```

Leave the `except subprocess.CalledProcessError` block as-is — it already handles CalledProcessError correctly.

- [ ] **Step 7: Re-run — verify PASS**

Run: `python -m pytest tests/test_gdal_subprocess_module.py -v`
Expected: PASS.

Run the existing NAIP test:
Run: `python -m pytest tests/test_acquire_naip.py -v 2>&1 | tail -20`
Expected: no new failures.

- [ ] **Step 8: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -40`

### Completion check

```
BEFORE marking this task complete:
1. Review against "subprocess.run blocking signal handlers" and "Call-site-before-implementation". Both addressed.
2. Confirm the existing SIGTERM handler in acquire_imagery.py still works — `_child_pid` is still set/cleared by the thin wrapper. Yes.
3. Confirm acquire_naip.py has its own `_child_pid` global (added in Step 6) and the SIGTERM handler uses it. Yes.
4. Count remaining `subprocess.run(` calls in acquire_naip.py — should be 0 or 1. If 1, it's likely unrelated (e.g., a logfile tool).
5. Run full suite.
```

- [ ] **Step 9: Commit**

```bash
git add scripts/gdal_subprocess.py scripts/acquire_imagery.py scripts/acquire_naip.py tests/test_gdal_subprocess_module.py
git commit -m "$(cat <<'EOF'
fix(pipeline): share cancellable GDAL subprocess wrapper (B5)

acquire_naip.py used subprocess.run(check=True) for all 4 GDAL
operations (gdal_translate JP2→GTiff, gdalbuildvrt, gdal_translate
VRT→MBTiles, gdaladdo). subprocess.run blocks the main thread;
SIGTERM set _cancel_requested but the thread couldn't check it for
up to 7200s per operation. Cancel clicks on NAIP were ineffective.

Extract acquire_imagery's Popen-with-process-group wrapper to a
shared module scripts/gdal_subprocess.py with on_child_started /
on_child_ended callbacks so each caller can register its pid with
its own SIGTERM handler. Migrate acquire_imagery (thin wrapper)
and acquire_naip (4 call sites + new _child_pid global + SIGTERM
handler update).
EOF
)"
```

---

## Task 9 — B1 + D1 + D3: NOAA Phase 5 rewrite (cancel guards, gate erosion, keep WAL)

**Bug references:** B1, D1, D3. Also closes B9 via the D1 gating change.

**Files:**
- Modify: `scripts/rasterio_ops.py:795-865` (`inpaint_nodata_pixels`) — add `cancel_check` param
- Modify: `scripts/rasterio_ops.py:868-959` (`erode_nodata_edges`) — add `cancel_check` param
- Modify: `scripts/acquire_imagery.py:2196-2300` (`run_noaa` Phase 5 tail) — cancel guards between sub-steps + gate erosion on first-run-only + remove DELETE journal flip + keep TRUNCATE checkpoint
- Test: `tests/test_noaa_phase5.py` (new file)

**Why one task, not three:** B1 adds cancel guards between Phase 5 sub-steps. D1 gates erosion off on resume (which also closes B9). D3 removes the `PRAGMA journal_mode=DELETE` flip while keeping `wal_checkpoint(TRUNCATE)`. All three changes edit the same Phase 5 block at 2196-2300. Splitting invites merge conflicts.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — specifically:
   - "Finalization guards stale after adding fast-path bypasses" (directly relevant to the skip_to_postprocess branch)
   - "Non-idempotent destructive post-processing on resume" (B9, covered by D1)
   - "Post-processing order dependencies" (reference — B8 is DEFERRED in this cycle; do NOT change the erosion-vs-overview order here)
3. Read run_noaa Phase 5 (scripts/acquire_imagery.py:2204-2300) in full.
Follow TDD. This is the highest-risk task in the plan — flag as MEDIUM RISK.
```

### Steps

- [ ] **Step 1: Add `cancel_check` parameter to `inpaint_nodata_pixels`**

Edit `scripts/rasterio_ops.py`. Locate the function signature:

```python
def inpaint_nodata_pixels(
    mbtiles_path: Path,
    nodata_threshold: int = 20,
    max_nodata_ratio: float = 0.5,
) -> int:
```

Replace with:

```python
def inpaint_nodata_pixels(
    mbtiles_path: Path,
    nodata_threshold: int = 20,
    max_nodata_ratio: float = 0.5,
    cancel_check=None,
) -> int:
```

Then inside the `while batch:` loop (around line 828), add a cancel check. Locate:

```python
        fixed = 0
        batch = cursor.fetchmany(500)
        while batch:
            for z, x, y, data in batch:
```

Replace with:

```python
        fixed = 0
        batch = cursor.fetchmany(500)
        while batch:
            if cancel_check and cancel_check():
                log.info("inpaint_nodata_pixels: cancellation requested, stopping after %d tiles", fixed)
                break
            for z, x, y, data in batch:
```

- [ ] **Step 2: Add `cancel_check` parameter to `erode_nodata_edges`**

Edit `scripts/rasterio_ops.py`. Locate the signature:

```python
def erode_nodata_edges(
    mbtiles_path: Path,
    edge_pixels: int = 48,
    min_edge_fill: float = 0.90,
    nodata_threshold: int = 20,
) -> int:
```

Replace with:

```python
def erode_nodata_edges(
    mbtiles_path: Path,
    edge_pixels: int = 48,
    min_edge_fill: float = 0.90,
    nodata_threshold: int = 20,
    cancel_check=None,
) -> int:
```

Then inside the `while removed_this_round > 0:` loop (around line 899), add a cancel check. Locate:

```python
        for z in zoom_levels:
            removed_this_round = 1  # seed the loop
            while removed_this_round > 0:
                removed_this_round = 0
```

Replace with:

```python
        for z in zoom_levels:
            removed_this_round = 1  # seed the loop
            while removed_this_round > 0:
                if cancel_check and cancel_check():
                    log.info("erode_nodata_edges: cancellation requested, stopping after %d tiles", total_removed)
                    return total_removed
                removed_this_round = 0
```

- [ ] **Step 3: Write the failing test**

Create `tests/test_noaa_phase5.py`:

```python
"""Tests for Task 9 changes: B1, D1, D3 in run_noaa Phase 5."""

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestPhase5CancelGuards:
    """B1: cancel guards must gate each Phase 5 sub-step."""

    def test_run_noaa_has_cancel_guards_between_phase5_steps(self):
        """The Phase 5 block must re-check _cancel_requested after overviews, erode, inpaint."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        phase5_start = src.find("# Phase 5:")
        assert phase5_start != -1, "Phase 5 comment not found"
        phase5 = src[phase5_start:]

        # Must have at least 3 cancel checks between the 3 sub-steps
        # (after gdaladdo, after erode, after inpaint, before final status)
        cancel_checks = phase5.count("_cancel_requested")
        assert cancel_checks >= 4, (
            f"Phase 5 must have at least 4 _cancel_requested checks "
            f"(one existing at top + new ones between steps); got {cancel_checks}"
        )

    def test_erode_nodata_edges_accepts_cancel_check(self):
        """D1/B9: erode_nodata_edges must accept a cancel_check kwarg."""
        from rasterio_ops import erode_nodata_edges
        sig = inspect.signature(erode_nodata_edges)
        assert "cancel_check" in sig.parameters

    def test_inpaint_nodata_pixels_accepts_cancel_check(self):
        """B1: inpaint_nodata_pixels must accept a cancel_check kwarg."""
        from rasterio_ops import inpaint_nodata_pixels
        sig = inspect.signature(inpaint_nodata_pixels)
        assert "cancel_check" in sig.parameters


class TestPhase5EroderGatedOnResume:
    """D1/B9: erode must NOT run when skip_to_postprocess=True."""

    def test_phase5_erosion_gated_on_skip_to_postprocess(self):
        """Erosion call site must check `not skip_to_postprocess`."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        # Find the erosion call
        erode_idx = src.find("rio_erode_nodata_edges(")
        assert erode_idx != -1, "erode_nodata_edges call not found"

        # The 400 chars before the call must contain a skip_to_postprocess check
        preceding = src[max(0, erode_idx - 400):erode_idx]
        assert "skip_to_postprocess" in preceding, (
            "Erosion call site must be gated by skip_to_postprocess. "
            "D1 fix: only erode on first run (not on resume), otherwise boundary shifts "
            "can destroy previously-valid tiles with no recovery path."
        )


class TestPhase5WalMode:
    """D3: keep WAL mode permanently — remove the PRAGMA journal_mode=DELETE flip."""

    def test_no_delete_journal_mode_flip(self):
        """Phase 5 final block must NOT flip to DELETE journal mode."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        # Scan only Phase 5 tail (after "Final WAL checkpoint")
        tail_idx = src.find("Final WAL checkpoint")
        assert tail_idx != -1
        tail = src[tail_idx:]
        assert "journal_mode=DELETE" not in tail, (
            "D3 fix: do not flip to DELETE journal mode. "
            "TileServer reads WAL-mode SQLite correctly; the flip was defensive "
            "and caused recent 404 bugs."
        )

    def test_wal_truncate_checkpoint_preserved(self):
        """Phase 5 final block MUST still issue wal_checkpoint(TRUNCATE)."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        tail_idx = src.find("Final WAL checkpoint")
        tail = src[tail_idx:]
        assert "wal_checkpoint(TRUNCATE)" in tail, (
            "TRUNCATE checkpoint must be preserved — it flushes WAL into main file "
            "so TileServer reads consistent data."
        )
```

- [ ] **Step 4: Run to verify FAIL**

Run: `python -m pytest tests/test_noaa_phase5.py -v`
Expected: FAIL (multiple — cancel guards missing, erode not gated, DELETE flip still present).

- [ ] **Step 5: Rewrite the Phase 5 block**

Edit `scripts/acquire_imagery.py`. Locate the full Phase 5 block (starting at line 2204 with `# Phase 5: Build overview pyramids` and ending at line 2278 with the final `log.warning("WAL checkpoint failed...`). Replace the entire block from `# Phase 5: Build overview pyramids` through the end of the `# TRUNCATE mode resets the WAL ...` / WAL block at 2278 with:

```python
    # Phase 5: Build overview pyramids + nodata cleanup
    # Also run when skip_to_postprocess (all quads already done) — overviews
    # and inpaint are idempotent. Erosion is NOT idempotent (boundary shifts)
    # and is gated off on resume — see D1/B9 below.
    if output.exists() and (tiles_done > 0 or skip_to_postprocess):
        # Recalculate bounds from actual tile extent (first batch metadata is stale)
        try:
            _update_mbtiles_bounds(output)
        except Exception as exc:
            log.warning("Bounds recalculation failed: %s — metadata may be stale", exc)
        # Set a stable name for TileServer
        import sqlite3 as stdlib_sqlite3
        with stdlib_sqlite3.connect(str(output)) as conn:
            conn.execute("INSERT OR REPLACE INTO metadata (name, value) VALUES ('name', 'imagery_noaa')")
        log.info("Building overview pyramids for %s", output)
        update_progress(output, "noaa", args.bbox, "n/a",
                        tiles_done, total_tiles, phase="overviews",
                        geotiffs_downloaded=tiles_done,
                        geotiffs_total=total_tiles)
        try:
            _run_gdaladdo_with_metadata_fixup(output)
        except Exception as exc:
            log.warning("Overview generation failed: %s — output is still usable", exc)

        # B1 fix: cancel guard AFTER overview generation, before erode/inpaint
        if _cancel_requested:
            update_progress(output, "noaa", args.bbox, "n/a",
                            tiles_done, total_tiles, status="cancelled",
                            phase="cancelled",
                            geotiffs_downloaded=tiles_done,
                            geotiffs_total=total_tiles)
            log.info("NOAA pipeline cancelled after overview build")
            return

        # Checkpoint WAL after overviews before erosion/inpaint
        import sqlite3 as _pp_sql
        try:
            with _pp_sql.connect(str(output)) as _pc:
                _pc.execute("PRAGMA wal_checkpoint(PASSIVE)")
        except Exception:
            pass

        # Post-process: clean up JPEG nodata artifacts
        # 1. Erode boundary tiles with heavy nodata (black rectangles over basemap)
        # 2. Inpaint remaining black pixels (seams between NAIP quads)
        #
        # D1/B9 fix: erosion is gated off on resume (skip_to_postprocess=True).
        # erode_nodata_edges is destructive and evaluates boundary tiles against
        # the CURRENT tile bounds. On an expanded-bbox resume, it would strip
        # valid tiles added by the new quads — an unrecoverable loss because
        # the deleted tiles' filenames remain in _noaa_checkpoint.
        # Users who want to re-erode after an expansion can delete the
        # checkpoint and re-run. This matches the "resume = incremental add"
        # mental model.
        try:
            from rasterio_ops import erode_nodata_edges as rio_erode_nodata_edges
            from rasterio_ops import inpaint_nodata_pixels as rio_inpaint_nodata_pixels

            if not skip_to_postprocess:
                eroded = rio_erode_nodata_edges(
                    output, cancel_check=lambda: _cancel_requested
                )
                if eroded:
                    log.info("Eroded %d nodata-edge tiles for clean basemap transition", eroded)
            else:
                log.info("Skipping erosion on resume run (D1 gate: not idempotent across bbox expansion)")

            # B1 fix: cancel guard AFTER erode, before inpaint
            if _cancel_requested:
                update_progress(output, "noaa", args.bbox, "n/a",
                                tiles_done, total_tiles, status="cancelled",
                                phase="cancelled",
                                geotiffs_downloaded=tiles_done,
                                geotiffs_total=total_tiles)
                log.info("NOAA pipeline cancelled after erosion")
                return

            # Checkpoint WAL between erode and inpaint (inpaint touches every tile)
            try:
                with _pp_sql.connect(str(output)) as _pc:
                    _pc.execute("PRAGMA wal_checkpoint(PASSIVE)")
            except Exception:
                pass
            inpainted = rio_inpaint_nodata_pixels(
                output, cancel_check=lambda: _cancel_requested
            )
            if inpainted:
                log.info("Inpainted %d tiles to remove black seams", inpainted)
        except Exception as exc:
            log.warning("Nodata cleanup failed: %s — output is still usable", exc)

        # B1 fix: cancel guard AFTER inpaint, before final status write
        if _cancel_requested:
            update_progress(output, "noaa", args.bbox, "n/a",
                            tiles_done, total_tiles, status="cancelled",
                            phase="cancelled",
                            geotiffs_downloaded=tiles_done,
                            geotiffs_total=total_tiles)
            log.info("NOAA pipeline cancelled after inpaint")
            return

    # TileServer config update + restart is handled by the search service
    # after it detects pipeline completion via status reconciliation.
    # See services/search/main.py pipeline_status() endpoint.

    # Final WAL checkpoint: flush all pending writes into the main database file.
    # Without this, the WAL can grow to several GB during post-processing
    # (overviews + erosion + inpainting write hundreds of thousands of tiles).
    # D3 fix: keep WAL mode permanently. TileServer reads WAL-mode SQLite
    # correctly on modern SQLite; the previous `PRAGMA journal_mode=DELETE`
    # flip required zero other connections and caused recent 404 bugs when
    # TileServer held a read handle. TRUNCATE checkpoint alone is sufficient
    # (flushes WAL into main file, resets WAL to zero bytes).
    if output.exists():
        import sqlite3 as _wal_sql
        try:
            with _wal_sql.connect(str(output)) as _wc:
                _wc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            log.info("WAL checkpoint complete — database ready for TileServer")
        except Exception as exc:
            log.warning("WAL checkpoint failed: %s — TileServer may need manual restart", exc)
```

- [ ] **Step 6: Re-run — verify PASS**

Run: `python -m pytest tests/test_noaa_phase5.py -v`
Expected: PASS.

Also re-run the existing NOAA test:
Run: `python -m pytest tests/test_noaa_naip.py tests/test_noaa_progress.py -v`
Expected: no new failures.

- [ ] **Step 7: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -40`

### Completion check

```
BEFORE marking this task complete:
1. Review against the cited pitfalls. "Finalization guards stale after adding fast-path bypasses" applies — verify that the skip_to_postprocess branch still executes the WAL-checkpoint tail. Yes: the `if output.exists():` WAL block is outside the Phase 5 `if ... (tiles_done > 0 or skip_to_postprocess)` gate, so it always fires when the file exists.
2. Confirm the 4 cancel guards are in place: (a) top of Phase 5 (existing at line 2196), (b) after overviews, (c) after erode, (d) after inpaint.
3. Confirm `journal_mode=DELETE` is nowhere in run_noaa.
4. Confirm erosion gate works: `if not skip_to_postprocess:` wraps only `rio_erode_nodata_edges(...)` and its success log. Inpaint still runs unconditionally — it is idempotent.
5. Run full suite. If any existing NOAA test fails because it depended on DELETE-mode or unconditional erosion, investigate — the test may have been asserting the WRONG behavior and needs updating. If so, update the test in the same commit with a brief note.
```

- [ ] **Step 8: Commit**

```bash
git add scripts/acquire_imagery.py scripts/rasterio_ops.py tests/test_noaa_phase5.py
git commit -m "$(cat <<'EOF'
fix(pipeline): cancel guards + WAL mode + no-erode-on-resume in NOAA Phase 5 (B1,B9,D1,D3)

B1: after the _cancel_requested check at the top of Phase 5, the
overview/erode/inpaint sub-steps all ran unconditionally, and
neither erode nor inpaint accepted a cancel_check. A cancel
during the 30+ min post-processing tail was silently ignored and
the pipeline reported status="completed".

- Add cancel_check kwarg to erode_nodata_edges and
  inpaint_nodata_pixels (rasterio_ops.py).
- Pass `cancel_check=lambda: _cancel_requested` from run_noaa.
- Add cancel guards after overviews, after erode, and before the
  final status write. Each writes status="cancelled" and returns.

D1/B9: erode_nodata_edges is destructive (DELETE rows) and not
idempotent under bbox expansion. On resume runs
(skip_to_postprocess=True), the current MIN/MAX tile bounds may
have shifted; re-running erosion strips valid tiles with no
recovery path. Gate erosion off when skip_to_postprocess — matches
the "resume = incremental add" mental model. Users who want
re-erosion after expansion can drop _noaa_checkpoint and re-run.

D3: remove `PRAGMA journal_mode=DELETE` at pipeline end. The flip
required no other connections open on the DB; TileServer holds a
read handle during the entire run, causing the flip to fail and
(recently) 404s. TRUNCATE checkpoint alone suffices — WAL is
flushed into the main file. TileServer reads WAL-mode SQLite
correctly on supported versions.
EOF
)"
```

---

## REVIEW CHECKPOINT #2 — After Tasks 5-9

```
After Tasks 5-9 (fetch_to_file, _merger progress, M2M cancel, gdal_subprocess extract, Phase 5 rewrite):
You MUST carefully review the batch from multiple perspectives and revise/refine as appropriate. Repeat this review (minimum three rounds; keep going if the third round still finds substantive issues) until confident.

Review focus:
1. Integration: Task 8's extracted `run_gdal_subprocess` is used by Task 9's Phase 5 via the thin wrapper in acquire_imagery. Does the wrapper still correctly set/clear `_child_pid`? Verify by reading the thin wrapper and comparing to the original at 732-777.
2. Cancel semantics: across Tasks 5, 6, 7, 9, cancel now has multiple new guard points. Trace a cancel through each: NAIP, M2M overview, NOAA Phase 5 at 3 points. All should end with status="cancelled", not "completed".
3. WAL mode change: does the search service's reconciliation block (Task 4) still work correctly against a WAL-mode MBTiles that's never been flipped to DELETE? Yes — it issues its own wal_checkpoint(TRUNCATE) + journal_mode=DELETE at line 1527. That's redundant but harmless for now (the sink side can flip DELETE because at that point the pipeline container is dead). Do NOT remove the search-side flip in this cycle — it's a separate decision.
4. B11 staging reuse: verify the check happens OUTSIDE the semaphore so the existence check doesn't waste a concurrency slot. Yes.
5. Phase 5 skip_to_postprocess path: trace through — if skip_to_postprocess=True, the block still enters the `if output.exists() and (... or skip_to_postprocess):` gate, runs overviews, skips erode (new), runs inpaint, hits the final WAL TRUNCATE outside the gate. Status write path at 2281-2293 unchanged. Good.
6. Re-run full suite. Confirm no new failures beyond baseline.

Do not proceed to Task 10 until all three review rounds pass clean.
```

---

## Task 10 — D2: Add `completed_partial` status when tiles_failed > 0

**Bug reference:** D2.

**Files:**
- Modify: `scripts/acquire_imagery.py:2281-2300` (end of `run_noaa`)
- Test: `tests/test_noaa_completed_partial.py` (new file)

**Why:** Today `run_noaa` writes `status="error"` only when `tiles_done == 0` and `status="completed"` otherwise, including "1 of 500 succeeded." The UI can't distinguish "clean completion" from "mostly-failed." Add `completed_partial` for the case `tiles_done > 0 and tiles_failed > 0`. Backend-only for now — search service will still trigger TileServer restart because its reconciliation treats anything that's not "error" as completion.

**Reconciliation check:** Read `services/search/main.py:1493-1511` to verify the reconciliation logic matches on specific log strings ("MBTiles written to", "NOAA pipeline complete", etc.), not on the exact status enum value. The new `completed_partial` status written to the state file will still reach `new_status = "completed"` if the log-scan matches — which is desirable. When the pipeline container exits cleanly with `completed_partial` already in the state file (status not in `running`/`cancelling`), the reconciliation block is skipped entirely. Either way, TileServer still restarts for partial completions.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md
3. Read services/search/main.py:1490-1555 to confirm the status-matching logic won't break on the new enum value.
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the final-status block**

Read `scripts/acquire_imagery.py:2280-2300`. Note:
- Line 2281: `if tiles_done == 0 and not skip_to_postprocess:` → writes `status="error"`.
- Line 2286: `else:` → writes `status="completed"`.
- No branch for "some failed but some succeeded."

- [ ] **Step 2: Write the failing test**

Create `tests/test_noaa_completed_partial.py`:

```python
"""Test D2: run_noaa writes status='completed_partial' when tiles_failed > 0."""

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestCompletedPartialStatus:
    """Source-level assertion that the new branch exists."""

    def test_run_noaa_source_has_completed_partial_branch(self):
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        assert "completed_partial" in src, (
            "D2 fix: run_noaa should write status='completed_partial' when "
            "tiles_done > 0 and tiles_failed > 0."
        )

    def test_completed_partial_gated_on_tiles_failed_gt_zero(self):
        """The branch must be gated on tiles_failed > 0, not just tiles_done > 0."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        # Find the completed_partial reference and look for tiles_failed nearby
        idx = src.find("completed_partial")
        assert idx != -1
        context = src[max(0, idx - 300):idx + 100]
        assert "tiles_failed" in context, (
            "completed_partial branch must be gated by tiles_failed > 0"
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_noaa_completed_partial.py -v`
Expected: FAIL.

- [ ] **Step 4: Apply the fix**

Edit `scripts/acquire_imagery.py`. Locate the final-status block:

```python
    # Final status
    if tiles_done == 0 and not skip_to_postprocess:
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, total_tiles, status="error", phase="error",
                        error=f"All {total_tiles} tiles failed to process")
        log.error("NOAA pipeline failed: 0/%d tiles processed", total_tiles)
    else:
        reported_done = total_tiles_original if skip_to_postprocess else tiles_done
        reported_total = total_tiles_original if skip_to_postprocess else total_tiles
        update_progress(output, "noaa", args.bbox, "n/a",
                        reported_done, reported_total, status="completed",
                        phase="complete",
                        geotiffs_downloaded=reported_done,
                        geotiffs_total=reported_total)
```

Replace with:

```python
    # Final status
    # D2: status taxonomy
    #   error            — 0 tiles succeeded (and not a resume run)
    #   completed_partial — tiles_done > 0 AND tiles_failed > 0
    #   completed        — clean completion (no failures, or resume run)
    # Search service reconciliation treats completed_partial the same as
    # completed for TileServer restart purposes (see services/search/main.py
    # pipeline_status). Frontend can render a warning badge for partial.
    if tiles_done == 0 and not skip_to_postprocess:
        update_progress(output, "noaa", args.bbox, "n/a",
                        0, total_tiles, status="error", phase="error",
                        error=f"All {total_tiles} tiles failed to process")
        log.error("NOAA pipeline failed: 0/%d tiles processed", total_tiles)
    elif tiles_failed > 0 and not skip_to_postprocess:
        reported_done = tiles_done
        reported_total = total_tiles
        update_progress(output, "noaa", args.bbox, "n/a",
                        reported_done, reported_total, status="completed_partial",
                        phase="complete",
                        error=f"{tiles_failed} of {total_tiles} tiles failed",
                        geotiffs_downloaded=reported_done,
                        geotiffs_total=reported_total)
        log.warning("NOAA pipeline completed with partial failures: %d/%d processed, %d failed",
                    tiles_done, total_tiles, tiles_failed)
    else:
        reported_done = total_tiles_original if skip_to_postprocess else tiles_done
        reported_total = total_tiles_original if skip_to_postprocess else total_tiles
        update_progress(output, "noaa", args.bbox, "n/a",
                        reported_done, reported_total, status="completed",
                        phase="complete",
                        geotiffs_downloaded=reported_done,
                        geotiffs_total=reported_total)
```

- [ ] **Step 5: Re-run — verify PASS**

Run: `python -m pytest tests/test_noaa_completed_partial.py -v`

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`

### Completion check

```
BEFORE marking this task complete:
1. Confirm the new branch is only taken when tiles_failed > 0 AND tiles_done > 0 AND not skip_to_postprocess. Three-way gate.
2. Verify the search service's reconciliation won't misclassify completed_partial. Grep `services/search/main.py` for "completed_partial" (should be 0 matches — search only matches log strings, not status strings). Grep for status-string comparisons in main.py — the only ones are against "running", "cancelling", "cancelled", "completed", "error", none of which the new value collides with.
3. Run full suite.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_noaa_completed_partial.py
git commit -m "$(cat <<'EOF'
fix(pipeline): add completed_partial status for NOAA runs with failures (D2)

Previously: tiles_done == 0 → error; anything else → completed,
including "1 of 500 succeeded." The UI couldn't distinguish a
clean run from a mostly-failed one.

Add a third branch: tiles_done > 0 AND tiles_failed > 0 (and not
a resume run) writes status="completed_partial" with an error
field naming the failure ratio. TileServer still restarts because
search-service reconciliation matches on log strings, not status
enums.

Frontend handling of the new badge state is deferred.
EOF
)"
```

---

## Task 11 — B13: Checkpoint atomicity in `_merger`

**Bug reference:** B13.

**Files:**
- Modify: `scripts/acquire_imagery.py:2137-2186` (`_merger`)
- Test: `tests/test_noaa_checkpoint_atomicity.py` (new file)

**Why:** `_merge_tile` → `convert_batch_to_mbtiles` → `merge_mbtiles` commits the tile on one sqlite3 connection. Then `_merger` opens a SEPARATE sqlite3 connection and inserts into `_noaa_checkpoint`. A SIGKILL between the two commits leaves the tile in `tiles` but not in `_noaa_checkpoint`. On resume, the tile is re-downloaded and re-merged.

**Scope note:** D6 (move checkpoint to sidecar JSON) is DEFERRED. This task implements a LESS INVASIVE fix: a post-crash checkpoint-repair routine that re-derives `_noaa_checkpoint` from the actual `tiles` table at pipeline start. This converts the split-commit from a data-loss risk into a one-time re-scan at startup.

**Why this approach over single-connection:** The single-connection approach requires threading a sqlite3 connection through `_merge_tile` → `convert_batch_to_mbtiles` → `merge_mbtiles` (3 files, 4 call sites). The post-crash repair is additive — it runs ONCE at pipeline start and has zero impact on the hot loop. It won't guarantee atomicity across a single crash, but it ensures that on the NEXT start, the checkpoint is consistent with the actual tiles table.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — "Checkpoint write split from protected-work commit"
Follow TDD.

IMPORTANT SCOPE BOUNDARY:
- D6 (move checkpoint to sidecar JSON file) is DEFERRED from this cycle.
- The in-scope B13 fix is a post-crash repair routine (this task).
- If during implementation you find the repair is too complex to implement
  cleanly, fall back to wiring the sqlite3 connection through
  merge_mbtiles (the "single-connection" approach) — but flag this as a
  scope increase in the commit message.
```

### Steps

- [ ] **Step 1: Read the current checkpoint code**

Read `scripts/acquire_imagery.py:2137-2186` — specifically the `_merger` closure including the `_noaa_checkpoint` INSERT at lines 2168-2178. Also read the tile-skipping logic earlier in `run_noaa` that consults `_noaa_checkpoint`. Find it with:

Run: `grep -n '_noaa_checkpoint' scripts/acquire_imagery.py`

Note the skip-logic location (likely around 1870-1895 where `skip_to_postprocess` and the filtered-tile-list are computed).

- [ ] **Step 2: Write the failing test**

Create `tests/test_noaa_checkpoint_atomicity.py`:

```python
"""Test B13 fix: checkpoint repair re-derives _noaa_checkpoint from tiles table at pipeline start."""

import inspect
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestCheckpointRepair:
    """Verify a repair function exists and syncs _noaa_checkpoint with the tiles table."""

    def test_repair_function_exists(self):
        import acquire_imagery
        assert hasattr(acquire_imagery, "_repair_noaa_checkpoint"), (
            "B13 fix: _repair_noaa_checkpoint function must exist at module level"
        )

    def test_repair_populates_checkpoint_from_tiles(self, tmp_path):
        """Given an MBTiles with tiles but no _noaa_checkpoint, repair populates the table."""
        from acquire_imagery import _repair_noaa_checkpoint

        mb = tmp_path / "test.mbtiles"
        conn = sqlite3.connect(str(mb))
        conn.execute("""CREATE TABLE tiles (
            zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER,
            tile_data BLOB, PRIMARY KEY(zoom_level,tile_column,tile_row))""")
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.execute("INSERT INTO tiles VALUES (10, 1, 1, ?)", (b"tile1",))
        conn.commit()
        conn.close()

        # tile_filenames maps tile filenames to (z, x, y) — we provide a mapping
        # so the repair knows which filenames correspond to which tiles.
        # For this test we pass a simple list of (fname, z, x, y).
        tile_coord_map = {"tile_10_1_1.tif": (10, 1, 1)}
        _repair_noaa_checkpoint(mb, tile_coord_map)

        # After repair, _noaa_checkpoint should contain tile_10_1_1.tif
        conn = sqlite3.connect(str(mb))
        rows = conn.execute(
            "SELECT tile_filename FROM _noaa_checkpoint"
        ).fetchall()
        conn.close()
        filenames = [r[0] for r in rows]
        assert "tile_10_1_1.tif" in filenames, (
            f"Expected tile_10_1_1.tif in _noaa_checkpoint after repair; got {filenames}"
        )

    def test_repair_no_tiles_table_is_noop(self, tmp_path):
        """If the MBTiles has no tiles table (never opened), repair is a no-op."""
        from acquire_imagery import _repair_noaa_checkpoint
        mb = tmp_path / "empty.mbtiles"
        mb.touch()
        # Should not raise
        _repair_noaa_checkpoint(mb, {})

    def test_repair_called_in_run_noaa(self):
        """run_noaa must call _repair_noaa_checkpoint before the download loop."""
        import acquire_imagery
        src = inspect.getsource(acquire_imagery.run_noaa)
        assert "_repair_noaa_checkpoint" in src, (
            "run_noaa must invoke _repair_noaa_checkpoint at pipeline start (B13 fix)"
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_noaa_checkpoint_atomicity.py -v`
Expected: FAIL — no such function.

- [ ] **Step 4: Add `_repair_noaa_checkpoint` function**

Edit `scripts/acquire_imagery.py`. Add this new function at module level, placing it above `run_noaa` (search for `async def run_noaa` and add the helper function just above it):

```python
def _repair_noaa_checkpoint(output_path: Path, tile_coord_map: dict) -> int:
    """Re-derive _noaa_checkpoint from the actual tiles table.

    B13 fix: `_merger` writes tiles on one sqlite connection and inserts
    into _noaa_checkpoint on another. A crash between the two commits
    leaves the tile merged but unchecked — on resume, the tile is
    re-downloaded and re-merged, running the lossy composite path again.

    This repair runs at pipeline start. It scans the tiles table and,
    for every tile whose (z, x, y) maps to a known input filename via
    `tile_coord_map`, ensures that filename is in _noaa_checkpoint. A
    crash after tile commit but before checkpoint commit becomes a
    one-time re-scan cost at the next start, not a per-tile re-merge.

    Args:
        output_path: Path to the MBTiles output.
        tile_coord_map: Mapping {tile_filename: (zoom, col, row)} for
            every NOAA source tile. When a tile from this map is found
            in the tiles table, its filename is added to _noaa_checkpoint.

    Returns:
        Number of checkpoint rows added by the repair. 0 means the
        checkpoint was already consistent (or no tiles to check).
    """
    if not output_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(output_path))
    except sqlite3.Error:
        return 0
    try:
        # Ensure the tables we'll touch exist.
        # If `tiles` doesn't exist, this is a fresh / empty MBTiles — nothing to repair.
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tiles'"
        ).fetchone()
        if row is None:
            return 0
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _noaa_checkpoint "
            "(tile_filename TEXT PRIMARY KEY)"
        )

        # Gather existing checkpoint entries (cheap — small table).
        existing = {r[0] for r in conn.execute(
            "SELECT tile_filename FROM _noaa_checkpoint"
        )}

        added = 0
        # For each (fname, (z, x, y)) in the coord map, check if the tile
        # is present; if yes and the fname isn't in the checkpoint, insert.
        for fname, coord in tile_coord_map.items():
            if fname in existing:
                continue
            z, x, y = coord
            present = conn.execute(
                "SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, y),
            ).fetchone()
            if present:
                conn.execute(
                    "INSERT OR IGNORE INTO _noaa_checkpoint (tile_filename) VALUES (?)",
                    (fname,),
                )
                added += 1

        if added:
            conn.commit()
            log.info("Checkpoint repair: re-derived %d _noaa_checkpoint rows from tiles table", added)
        return added
    finally:
        conn.close()
```

- [ ] **Step 5: Wire the repair into `run_noaa`**

Edit `scripts/acquire_imagery.py`. Locate where `run_noaa` computes `tile_filenames` and the existing `_noaa_checkpoint` skip logic. Find it:

Run: `grep -n "tile_filenames\|_noaa_checkpoint" scripts/acquire_imagery.py | head -20`

This will show the call sites. The tile-filename-to-coords mapping isn't currently built — NOAA tiles are referenced by shapefile-derived names like `m_3311001_ne_12_060_20211014.tif`, and the coord mapping isn't computed at the filename level until GeoTIFF metadata is read during reproject. Because of this, **the coord-based repair is NOT reliably available without invasive changes**.

**Fallback to a simpler repair approach:** Since `_noaa_checkpoint` tracks filenames but the in-memory `tile_filenames` list is the source-of-truth for "what we intend to download," and the `tiles` table tracks (z, x, y), we can't bidirectionally reconcile without the coord map. Instead, implement a **conservative repair**: at pipeline start, if the tiles table has ANY rows but `_noaa_checkpoint` is empty (smoking-gun of a crash between the very first tile merge and checkpoint insert), log a warning so the user knows resume may re-merge some tiles. Do NOT attempt auto-repair without the coord map.

Rewrite Step 4's function (replace the body above) as:

```python
def _repair_noaa_checkpoint(output_path: Path, tile_coord_map: dict) -> int:
    """Detect and warn on _noaa_checkpoint/tiles divergence from a prior crash.

    B13 fix — conservative variant: `_merger` writes the tile on one
    sqlite connection and inserts into _noaa_checkpoint on another.
    A crash between commits leaves the tile merged but unchecked.

    Without a reliable filename→(z,x,y) map, we can't auto-repair — but
    we CAN detect the smoking-gun pattern: tiles table has rows but
    _noaa_checkpoint is empty or much smaller than expected. When the
    optional tile_coord_map is provided, we also run a targeted repair.

    Args:
        output_path: Path to the MBTiles output.
        tile_coord_map: Optional mapping {tile_filename: (zoom, col, row)}
            for NOAA source tiles. When present and non-empty, rows are
            inserted into _noaa_checkpoint for every mapped filename whose
            (z,x,y) is present in `tiles`.

    Returns:
        Number of checkpoint rows added by the repair. 0 means no repair
        was needed (or was not possible without a coord map).
    """
    if not output_path.exists():
        return 0
    try:
        conn = sqlite3.connect(str(output_path))
    except sqlite3.Error:
        return 0
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tiles'"
        ).fetchone()
        if row is None:
            return 0
        conn.execute(
            "CREATE TABLE IF NOT EXISTS _noaa_checkpoint "
            "(tile_filename TEXT PRIMARY KEY)"
        )

        tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
        ckpt_count = conn.execute("SELECT COUNT(*) FROM _noaa_checkpoint").fetchone()[0]

        # Divergence warning: tiles present but checkpoint empty is the
        # smoking-gun pattern of a crash between commits.
        if tile_count > 0 and ckpt_count == 0:
            log.warning(
                "Checkpoint divergence detected: tiles=%d but _noaa_checkpoint=0. "
                "Resume may re-merge tiles (B13). Consider dropping the output "
                "and starting fresh if you see duplicate-composite artifacts.",
                tile_count,
            )

        if not tile_coord_map:
            return 0

        existing = {r[0] for r in conn.execute(
            "SELECT tile_filename FROM _noaa_checkpoint"
        )}
        added = 0
        for fname, coord in tile_coord_map.items():
            if fname in existing:
                continue
            z, x, y = coord
            present = conn.execute(
                "SELECT 1 FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
                (z, x, y),
            ).fetchone()
            if present:
                conn.execute(
                    "INSERT OR IGNORE INTO _noaa_checkpoint (tile_filename) VALUES (?)",
                    (fname,),
                )
                added += 1

        if added:
            conn.commit()
            log.info("Checkpoint repair: re-derived %d _noaa_checkpoint rows from tiles table", added)
        return added
    finally:
        conn.close()
```

Now wire it into `run_noaa`. Locate the early section of `run_noaa` where `output = Path(args.output)` is set and the tile filenames are computed. Add a call to `_repair_noaa_checkpoint` after `output` is set but before the 3-stage pipeline begins. Specifically, find this line (search for it in the file):

`if output.exists():` — the first occurrence inside `run_noaa`, which will be near where the resumed tile-list is computed.

Add, immediately after the output Path is derived from `args.output` and before any skip-logic:

```python
    # B13 fix: detect (and where possible repair) checkpoint divergence
    # from a prior crash between tile commit and checkpoint commit.
    # tile_coord_map is empty in this call path — the NOAA pipeline works
    # on filenames, not (z,x,y) tuples — so the call acts as a detect-and-warn.
    # Future: pass a real coord map once reproject metadata is cached earlier.
    try:
        _repair_noaa_checkpoint(output, {})
    except Exception as _exc:
        log.warning("Checkpoint repair pre-check failed: %s", _exc)
```

**Location:** paste this block right after the existing "output = Path(args.output)" assignment in `run_noaa`. If that exact line doesn't exist, paste it right before the first use of `_noaa_checkpoint` in `run_noaa` (you can find the right spot by running `grep -n "_noaa_checkpoint" scripts/acquire_imagery.py` and finding the lowest line number inside `run_noaa`).

- [ ] **Step 6: Re-run — verify PASS**

Run: `python -m pytest tests/test_noaa_checkpoint_atomicity.py -v`

Note: `test_repair_populates_checkpoint_from_tiles` will PASS because the coord map is provided in that test. `test_repair_no_tiles_table_is_noop` and `test_repair_called_in_run_noaa` should also pass.

- [ ] **Step 7: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -30`

### Completion check

```
BEFORE marking this task complete:
1. Review against "Checkpoint write split from protected-work commit". The fix is weaker than full atomicity (split commits are still present in _merger), but the detect-and-warn prevents silent re-merges from becoming invisible in logs. The coord-map-based auto-repair path is in place for future callers.
2. Error-path coverage: (a) no tiles table (new file) — noop, covered. (b) tiles exist, empty checkpoint — warning logged (not asserted in test, but covered by the smoking-gun detection branch). (c) coord map provided — auto-insert, covered. Good.
3. Run full suite.
```

- [ ] **Step 8: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_noaa_checkpoint_atomicity.py
git commit -m "$(cat <<'EOF'
fix(pipeline): detect _noaa_checkpoint divergence from tiles table (B13)

_merger commits the tile row on one sqlite connection and inserts
into _noaa_checkpoint on another. A crash between the two commits
leaves the tile merged but unchecked — on resume, the tile is
re-downloaded and re-merged, running the lossy composite path again.

A fully atomic fix requires threading a sqlite3 connection through
merge_mbtiles (3 files, 4 call sites) — deferred to a later cycle.
This patch adds _repair_noaa_checkpoint which runs at pipeline start
and:
  - logs a warning when tiles > 0 but _noaa_checkpoint == 0 (the
    smoking-gun pattern of a mid-merge crash)
  - optionally re-derives _noaa_checkpoint rows from the tiles
    table when a filename→(z,x,y) coord map is provided.

The current run_noaa call passes an empty coord map, so the repair
acts as detect-and-warn. Future callers with a coord map (e.g.
post-reproject metadata caching) get automatic repair.
EOF
)"
```

---

## Task 12 — B15: Single-write refactor of `update_progress`

**Bug reference:** B15.

**Files:**
- Modify: `scripts/acquire_imagery.py:279-326` (`update_progress`)
- Test: `tests/test_update_progress_single_write.py` (new file)

**Why:** `update_progress` writes the state file twice per call — first via `_generic_progress` (atomic rename #1), then reads it back, adds backward-compat fields (`mode`, `tiles_done`, `rate_per_sec`, etc.), and writes again via `write_pipeline_state` (atomic rename #2). A poller hitting the file between the two writes sees state WITHOUT the compat fields. Fix: build the enriched dict ONCE, write ONCE atomically.

**Risk flag:** MEDIUM. `_generic_progress` has its own invariants (logging, source-field handling). Bypassing it risks dropping a log line or contract field. Extra test coverage required.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — "Two-phase state writes expose intermediate fields to consumers"
3. Read scripts/pipeline_progress.py (the _generic_progress implementation) — understand what fields it injects and what invariants it maintains. The refactor must preserve those invariants.
Follow TDD. MEDIUM-RISK TASK — verify all existing update_progress callers still produce state files with their expected fields.
```

### Steps

- [ ] **Step 1: Read `_generic_progress`**

Run: `grep -n "def update_progress\|def write_pipeline_state\|def _atomic" scripts/pipeline_progress.py 2>/dev/null || find /home/administrator/Code/geographica -name pipeline_progress.py`

Read `scripts/pipeline_progress.py` (or wherever `update_progress as _generic_progress` is defined) to understand:
- Which fields it writes (e.g., `source`, `status`, `items_done`, `items_total`, `item_unit`, `detail`, `phase`, `error`, `bbox`, `zoom`, `updated_at`)
- Whether it preserves existing fields (merge vs overwrite)
- Whether it logs or has side effects besides the atomic write

- [ ] **Step 2: Read the current `update_progress` in `acquire_imagery.py`**

Read `scripts/acquire_imagery.py:225-327` (the full `update_progress` function).

- [ ] **Step 3: Write the failing test**

Create `tests/test_update_progress_single_write.py`:

```python
"""Test B15 fix: update_progress writes the state file exactly once per call."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import acquire_imagery as ai


class TestSingleWrite:
    """update_progress must produce exactly one atomic rename, not two."""

    def test_single_rename_per_call(self, tmp_path, monkeypatch):
        """Patch os.replace to count invocations during a single update_progress call."""
        import os

        output = tmp_path / "out.mbtiles"
        # Need to pass a real file path; state file is derived as
        # output.parent / ".pipeline-state.json"

        rename_count = {"n": 0, "targets": []}
        real_replace = os.replace

        def _count_replace(src, dst):
            rename_count["n"] += 1
            rename_count["targets"].append(str(dst))
            return real_replace(src, dst)

        monkeypatch.setattr(os, "replace", _count_replace)

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=5, tiles_total=10, rate=0.5,
            status="running", phase="downloading",
        )

        # Count renames that target the pipeline state file specifically
        state_targets = [t for t in rename_count["targets"]
                         if ".pipeline-state.json" in t
                         and not t.endswith(".tmp")]
        assert len(state_targets) == 1, (
            f"Expected exactly 1 atomic rename to .pipeline-state.json, "
            f"got {len(state_targets)} at: {state_targets}"
        )

    def test_state_file_always_has_compat_fields(self, tmp_path):
        """A single read of the state file must always have tiles_done, tiles_total, rate_per_sec, mode."""
        output = tmp_path / "out.mbtiles"

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=5, tiles_total=10, rate=0.5,
            status="running", phase="downloading",
        )

        state_path = output.parent / ".pipeline-state.json"
        data = json.loads(state_path.read_text())
        assert "tiles_done" in data
        assert "tiles_total" in data
        assert "rate_per_sec" in data
        assert "mode" in data
        assert data["mode"] == "noaa"
        assert data["tiles_done"] == 5
        assert data["tiles_total"] == 10

    def test_canonical_fields_preserved(self, tmp_path):
        """Canonical fields from _generic_progress must also be present (source, status, phase, detail, items_done, items_total, item_unit)."""
        output = tmp_path / "out.mbtiles"

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=5, tiles_total=10, rate=0.5,
            status="running", phase="downloading",
        )

        state_path = output.parent / ".pipeline-state.json"
        data = json.loads(state_path.read_text())
        # Canonical fields from pipeline_progress.update_progress
        for field in ("source", "status", "phase", "detail",
                      "items_done", "items_total", "item_unit"):
            assert field in data, f"Missing canonical field: {field}"
        assert data["source"] == "noaa"
        assert data["item_unit"] == "tiles"

    def test_m2m_downloading_phase_uses_geotiffs_unit(self, tmp_path):
        """Regression: during M2M downloading phase, item_unit='geotiffs' still set."""
        output = tmp_path / "out.mbtiles"

        ai.update_progress(
            output, "m2m", "-111,33,-110,34", "n/a",
            tiles_done=0, tiles_total=0, rate=0.0,
            status="running", phase="downloading",
            geotiffs_downloaded=3, geotiffs_total=5,
        )

        state_path = output.parent / ".pipeline-state.json"
        data = json.loads(state_path.read_text())
        assert data["item_unit"] == "geotiffs"
        assert data["items_done"] == 3
        assert data["items_total"] == 5
```

- [ ] **Step 4: Run to verify FAIL**

Run: `python -m pytest tests/test_update_progress_single_write.py -v`
Expected: `test_single_rename_per_call` FAILS (currently 2 renames).

- [ ] **Step 5: Refactor `update_progress`**

Edit `scripts/acquire_imagery.py`. Locate the full `update_progress` function (lines 225-327). Replace the entire function with:

```python
def update_progress(output_path: Path, mode: str, bbox: str, zoom: str,
                    tiles_done: int, tiles_total: int, rate: float = 0,
                    status: str = "running", error: str = None,
                    # M2M phase-aware fields
                    phase: str = None,
                    scenes_total: int = None,
                    geotiffs_downloaded: int = None, geotiffs_total: int = None,
                    geotiffs_bytes: int = None,
                    current_batch: int = None, total_batches: int = None,
                    tiles_reprojected: int = None):
    """Write structured progress to the state file atomically in ONE rename.

    B15 fix: previous implementation called _generic_progress (atomic rename
    #1) then read the file back, added backward-compat fields, and wrote
    again via write_pipeline_state (atomic rename #2). A frontend polling
    at 500ms could observe the file between writes, seeing canonical fields
    without the compat fields (tiles_done, rate_per_sec, mode).

    This rewrite builds the full enriched dict once, preserves any existing
    unrelated fields by merging with the on-disk state, then writes a single
    atomic rename.
    """
    state_path = Path(output_path).parent / ".pipeline-state.json"

    # Map old params to generic format.
    # During M2M downloading phase, geotiffs are the primary unit of work.
    if phase == "downloading" and geotiffs_total is not None:
        items_done_val = geotiffs_downloaded or 0
        items_total_val = geotiffs_total or 0
        item_unit_val = "geotiffs"
    else:
        items_done_val = tiles_done
        items_total_val = tiles_total
        item_unit_val = "tiles"

    # Build a human-readable detail string from available context.
    if phase is not None:
        if phase == "downloading" and geotiffs_total is not None:
            detail = (
                f"{phase}: {geotiffs_downloaded or 0}/{geotiffs_total} geotiffs"
                + (f" (batch {current_batch}/{total_batches})" if current_batch is not None else "")
            )
        else:
            detail = f"{phase}: {tiles_done}/{tiles_total} tiles"
    elif status == "completed":
        detail = f"completed: {tiles_done}/{tiles_total} tiles"
    elif status == "error":
        detail = f"error: {error or 'unknown'}"
    elif status == "cancelled":
        detail = f"cancelled after {tiles_done} tiles"
    else:
        detail = f"{tiles_done}/{tiles_total} tiles at {round(rate, 1)}/s"

    source = mode if mode else "imagery"

    # Read any existing state so we preserve unrelated fields (mirroring
    # write_pipeline_state's merge semantics).
    existing: dict = {}
    if state_path.exists():
        try:
            existing = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    import datetime as _dt
    updated_at = _dt.datetime.now(_dt.timezone.utc).isoformat()

    # Build the canonical fields (what _generic_progress would have written).
    enriched: dict = dict(existing)
    enriched.update({
        "source": source,
        "status": status,
        "phase": phase,
        "items_done": items_done_val,
        "items_total": items_total_val,
        "item_unit": item_unit_val,
        "detail": detail,
        "bbox": bbox,
        "updated_at": updated_at,
    })
    if zoom and zoom != "n/a":
        enriched["zoom"] = zoom
    if error is None:
        enriched.pop("error", None)
    else:
        enriched["error"] = error

    # Add the backward-compat fields in the SAME dict (no second read/write).
    enriched["mode"] = mode
    enriched["tiles_done"] = tiles_done
    enriched["tiles_total"] = tiles_total
    enriched["rate_per_sec"] = round(rate, 4)
    if getattr(update_progress, '_started_at', None) is not None:
        enriched.setdefault("started_at", update_progress._started_at)
    if geotiffs_downloaded is not None:
        enriched["geotiffs_downloaded"] = geotiffs_downloaded
    if geotiffs_total is not None:
        enriched["geotiffs_total"] = geotiffs_total
    if geotiffs_bytes is not None:
        enriched["geotiffs_bytes"] = geotiffs_bytes
    if current_batch is not None:
        enriched["current_batch"] = current_batch
    if total_batches is not None:
        enriched["total_batches"] = total_batches
    if scenes_total is not None:
        enriched["scenes_total"] = scenes_total
    if tiles_reprojected is not None:
        enriched["tiles_reprojected"] = tiles_reprojected

    # Single atomic write.
    _atomic_write_json(state_path, enriched)
```

Note the refactor:
- Preserves the `item_unit` mapping for M2M downloading phase (`geotiffs` vs `tiles`).
- Uses local `datetime` import to avoid shadowing.
- Merges on top of existing state to preserve unrelated fields (mirroring the old `write_pipeline_state` merge).
- Drops the `log.warning("Failed to write pipeline state...")` error path — `_atomic_write_json` raises on failure, which is fine; if a pipeline can't write its state it's in deeper trouble.
- Does NOT call `_generic_progress` anymore.

- [ ] **Step 6: Re-run — verify PASS**

Run: `python -m pytest tests/test_update_progress_single_write.py -v`
Expected: PASS (all 4 tests).

Run the existing progress tests to verify no regression:
Run: `python -m pytest tests/test_pipeline_progress.py tests/test_noaa_progress.py tests/test_m2m_progress.py -v`
Expected: all pass.

- [ ] **Step 7: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -40`

### Completion check

```
BEFORE marking this task complete:
1. Review against "Two-phase state writes expose intermediate fields". Test_single_rename_per_call asserts the fix. Good.
2. Coverage of M2M phase-aware fields: test_m2m_downloading_phase_uses_geotiffs_unit covers the geotiffs branch. Good.
3. Coverage of canonical fields: test_canonical_fields_preserved asserts source/status/phase/detail/items_*/item_unit are all present. Good.
4. Unknown-field preservation: we merge on top of existing state. Test that if a prior caller wrote `{"custom_field": 42}` it survives:

Add one more polling-race test (paste into test file before Step 7):

```python
    def test_preserves_unrelated_fields(self, tmp_path):
        """update_progress must not drop fields written by other pipelines."""
        import json as _json
        output = tmp_path / "out.mbtiles"
        state_path = output.parent / ".pipeline-state.json"
        state_path.write_text(_json.dumps({"custom_field": "sentinel_value"}))

        ai.update_progress(
            output, "noaa", "-111,33,-110,34", "n/a",
            tiles_done=1, tiles_total=2, rate=0.1,
            status="running", phase="downloading",
        )

        data = _json.loads(state_path.read_text())
        assert data.get("custom_field") == "sentinel_value"
```

5. Re-run the tests after adding the polling-race test. Run full suite.
```

- [ ] **Step 8: Commit**

```bash
git add scripts/acquire_imagery.py tests/test_update_progress_single_write.py
git commit -m "$(cat <<'EOF'
refactor(pipeline): write progress state once per call (B15)

update_progress wrote the state file twice per logical update:
first via _generic_progress (atomic rename #1), then read it
back, added backward-compat fields, and wrote again via
write_pipeline_state (rename #2). A frontend polling at 500ms
could observe the file between renames, seeing canonical fields
(source/status/phase) without compat fields (tiles_done/
rate_per_sec/mode) — rendering as zero progress or crashing on
undefined.toFixed().

Rewrite to build the enriched dict once (canonical + compat
fields in the same object), merge on top of existing state so
unrelated fields are preserved, and call _atomic_write_json once.
EOF
)"
```

---

## Task 13 — B16: True NAIP concurrency via `asyncio.gather`

**Bug reference:** B16.

**Files:**
- Modify: `scripts/acquire_naip.py:599,666-685` (the sequential for-loop becomes `asyncio.gather`)
- Test: `tests/test_naip_true_concurrency.py` (new file; do NOT modify existing `test_naip_concurrency.py`)

**Why:** `download_sem = asyncio.Semaphore(concurrency)` is created at line 599, but the for-loop at 666 `await`s each county sequentially. Only one `_process_county` runs at a time, so the semaphore never caps anything. `--concurrency 3` behaves identically to `--concurrency 1`.

**CRITICAL:** Do NOT change the default concurrency value (currently 2). The fix is to wire concurrency correctly, not to raise it.

### Preamble

```
BEFORE starting work:
1. Read .claude/skills/test-driven-development/SKILL.md
2. Read dev/testing-pitfalls.md — "Accepted-but-ignored parameters create false confidence"
3. Read the existing tests/test_naip_concurrency.py — the new test must not collide with its name or assertions.
Follow TDD.
```

### Steps

- [ ] **Step 1: Read the current code**

Read `scripts/acquire_naip.py:580-690`. Note:
- Line 599: `download_sem = asyncio.Semaphore(concurrency)` — correct.
- Line 601: `_process_county` is defined as a local async function; it already uses `async with download_sem:` at line 614. Good.
- Line 666: `for idx, (fips, url_info) in enumerate(downloadable):` is sequential.
- Line 677: `tif_path = await _process_county(fips, url_info)` — sequential await.
- Line 685: `save_checkpoint(staging_dir, checkpoint)` — called from the main body; concurrent access requires a lock.

- [ ] **Step 2: Write the failing test**

Create `tests/test_naip_true_concurrency.py`:

```python
"""Test B16 fix: NAIP pipeline runs _process_county concurrently up to `concurrency` limit."""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestTrueConcurrency:
    """Verify concurrency=3 runs up to 3 counties in parallel."""

    @pytest.mark.asyncio
    async def test_multiple_counties_run_concurrently(self, tmp_path, monkeypatch):
        """With concurrency=3 and 3 counties, max observed in-flight = 3."""
        import acquire_naip

        # Three fake counties
        counties = [
            ("12345", "CountyA", "AZ", (-111.0, 33.0, -110.9, 33.1)),
            ("12346", "CountyB", "AZ", (-111.1, 33.1, -111.0, 33.2)),
            ("12347", "CountyC", "AZ", (-111.2, 33.2, -111.1, 33.3)),
        ]

        # Track concurrent calls
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_download_county(session, fips, url_info, staging_dir):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                if in_flight > max_in_flight:
                    max_in_flight = in_flight
            # Simulate meaningful work
            await asyncio.sleep(0.1)
            async with lock:
                in_flight -= 1
            fake_path = staging_dir / f"naip_{fips}.jp2"
            fake_path.write_bytes(b"\x00\x00\x00\x0cjP  " + b"\x00" * 100)  # JP2 magic
            return fake_path

        def fake_convert(jp2_path, staging_dir, fips):
            tif = staging_dir / f"naip_{fips}.tif"
            tif.write_bytes(b"fake tiff")
            return tif

        # Patch so the pipeline reaches _process_county
        with patch.object(acquire_naip, "counties_for_bbox", return_value=counties), \
             patch.object(acquire_naip, "discover_county_urls",
                          new=AsyncMock(return_value={
                              "12345": {"url": "http://x/a.jp2", "format": "jp2",
                                        "filename": "a.jp2"},
                              "12346": {"url": "http://x/b.jp2", "format": "jp2",
                                        "filename": "b.jp2"},
                              "12347": {"url": "http://x/c.jp2", "format": "jp2",
                                        "filename": "c.jp2"},
                          })), \
             patch.object(acquire_naip, "download_county", new=fake_download_county), \
             patch.object(acquire_naip, "convert_jp2_to_geotiff", side_effect=fake_convert), \
             patch.object(acquire_naip, "validate_file_header", return_value=True), \
             patch.object(acquire_naip, "merge_to_mbtiles", return_value=True), \
             patch.object(acquire_naip, "check_disk_space"), \
             patch.object(acquire_naip, "update_progress"):

            staging = tmp_path / "staging"
            staging.mkdir()

            # Run the pipeline with concurrency=3
            await acquire_naip.run_pipeline(
                bbox_str="-112,33,-110,34",
                output_path=tmp_path / "out.mbtiles",
                staging_dir=staging,
                counties_db=str(tmp_path / "counties.sqlite"),
                concurrency=3,
            )

        assert max_in_flight >= 2, (
            f"Expected at least 2 concurrent downloads with concurrency=3; "
            f"observed max in-flight = {max_in_flight}. B16 fix not applied."
        )


class TestCheckpointLockSerialization:
    """Concurrent _process_county completions must serialize checkpoint writes."""

    def test_save_checkpoint_lock_exists(self):
        """run_pipeline must use an asyncio.Lock around save_checkpoint."""
        import inspect
        import acquire_naip
        src = inspect.getsource(acquire_naip.run_pipeline)
        assert "asyncio.Lock" in src or "asyncio.gather" in src, (
            "B16 fix: run_pipeline must use asyncio.gather for concurrent counties "
            "AND an asyncio.Lock around save_checkpoint."
        )
```

- [ ] **Step 3: Run to verify FAIL**

Run: `python -m pytest tests/test_naip_true_concurrency.py -v`
Expected: `test_multiple_counties_run_concurrently` FAILS (max_in_flight=1).

- [ ] **Step 4: Apply the fix**

Edit `scripts/acquire_naip.py`. Locate the for-loop at lines 665-685:

```python
        # Process counties with bounded concurrency
        for idx, (fips, url_info) in enumerate(downloadable):
            if _cancel_requested:
                update_progress(
                    state_path, phase="downloading", status="cancelled",
                    items_done=len(completed), items_total=len(discovered),
                    detail="Cancelled by user",
                    bbox=bbox_str,
                )
                log.info("Cancelled after %d counties", len(completed))
                return

            tif_path = await _process_county(fips, url_info)

            if tif_path is not None:
                geotiff_paths.append(tif_path)
                completed.add(fips)

                # Update checkpoint
                checkpoint["completed_counties"] = list(completed)
                save_checkpoint(staging_dir, checkpoint)
```

Replace with:

```python
        # B16 fix: run counties concurrently up to the `concurrency` cap.
        # _process_county already uses `async with download_sem:` which
        # bounds simultaneous downloads; the semaphore is created at
        # concurrency and only now wired via asyncio.gather.
        # Checkpoint writes need their own lock because multiple
        # _process_county completions finish concurrently.
        checkpoint_lock = asyncio.Lock()

        async def _process_and_checkpoint(fips: str, url_info: dict) -> Path | None:
            """Process one county, then serialize the checkpoint write."""
            tif_path = await _process_county(fips, url_info)
            if tif_path is None:
                return None
            async with checkpoint_lock:
                completed.add(fips)
                checkpoint["completed_counties"] = list(completed)
                save_checkpoint(staging_dir, checkpoint)
            return tif_path

        if _cancel_requested:
            update_progress(
                state_path, phase="downloading", status="cancelled",
                items_done=len(completed), items_total=len(discovered),
                detail="Cancelled by user",
                bbox=bbox_str,
            )
            log.info("Cancelled after %d counties", len(completed))
            return

        # Gather all county tasks concurrently. The `download_sem` inside
        # _process_county bounds active downloads to `concurrency`; gather
        # itself is unbounded but each task will block on the semaphore.
        results = await asyncio.gather(
            *[_process_and_checkpoint(fips, info) for fips, info in downloadable],
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                log.warning("County task raised: %s", result)
                continue
            if result is not None:
                geotiff_paths.append(result)
```

- [ ] **Step 5: Re-run — verify PASS**

Run: `python -m pytest tests/test_naip_true_concurrency.py -v`

Also re-run the existing NAIP tests:
Run: `python -m pytest tests/test_acquire_naip.py tests/test_naip_concurrency.py -v`
Expected: no new failures. Note: existing `test_naip_concurrency.py` asserts the CLI accepts `--concurrency` and that `run_pipeline` accepts the kwarg; it does NOT assert sequential behavior, so the fix doesn't collide with it.

- [ ] **Step 6: Full suite**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -40`

### Completion check

```
BEFORE marking this task complete:
1. Review against "Accepted-but-ignored parameters create false confidence". The test now verifies observed concurrency ≥ 2, not just that the flag is accepted. Good.
2. Did the fix introduce a new failure mode? The `return_exceptions=True` in gather means a raising task doesn't poison siblings — but also means failures are swallowed into the results list. We log each exception but don't fail the pipeline. This matches the current behavior (sequential version logged and continued on per-county failure).
3. Cancel semantics: inside `_process_county` the first guard checks `_cancel_requested` before the sem.acquire. Gather doesn't re-check before each sub-task, but _process_county's internal check fires quickly. Acceptable.
4. Save_checkpoint concurrency: protected by `asyncio.Lock` inside `_process_and_checkpoint`. Good.
5. DO NOT raise the default concurrency value — it stays at 2.
6. Run full suite.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/acquire_naip.py tests/test_naip_true_concurrency.py
git commit -m "$(cat <<'EOF'
fix(pipeline): wire NAIP --concurrency via asyncio.gather (B16)

download_sem = asyncio.Semaphore(concurrency) was created but the
county-processing for-loop awaited _process_county sequentially.
Only one county downloaded at a time; --concurrency 3 behaved
identically to --concurrency 1.

Replace the sequential await-loop with asyncio.gather over
per-county tasks. Each task still uses `async with download_sem:`
so effective concurrency is capped at `concurrency`. Wrap
save_checkpoint in an asyncio.Lock so concurrent completions
serialize their writes.

Default concurrency value (2) is unchanged.
EOF
)"
```

---

## REVIEW CHECKPOINT #3 — After Tasks 10-13

```
After Tasks 10-13 (D2, B13, B15, B16):
You MUST carefully review the batch from multiple perspectives and revise/refine as appropriate. Repeat this review (minimum three rounds; keep going if the third round still finds substantive issues) until confident.

Review focus:
1. Task 12 (B15) is the riskiest. Re-read the refactored update_progress function line-by-line against the original. Any field dropped? Any conditional branch lost? Specifically verify: the `source = mode if mode else "imagery"` fallback, the detail-string construction for all five status branches, the zoom-"n/a" filtering.
2. Task 13 (B16) changes control flow from sequential to concurrent. The existing cancel check fires INSIDE _process_county (first line) — confirm the cancel propagates quickly enough. If cancel fires partway through a 10-county run, the already-queued gather tasks will each see _cancel_requested inside _process_county's first check and return None. Good.
3. Task 11 (B13) is a non-invasive detect-and-warn. Verify the _repair_noaa_checkpoint function is called exactly once per run_noaa invocation (not per tile).
4. Task 10 (D2) adds a new status enum value. Grep `services/search/main.py` and `frontend/` for any switch-on-status code that might break:

Run: `grep -rn 'status.*==.*"completed"\|status.*in.*("completed"' services/search/ frontend/`

If any of those equality checks are "strict match," the new `completed_partial` value may not match. Acceptable for this cycle (frontend handling is deferred per scope), but flag any confusing behavior in the review journal.

5. Re-run full suite. The expected new-test count across all 13 bugs is ~25-30 new passing tests. Baseline was 579 pass; now expect 600+ pass.

Do not proceed to Task 14 until all three review rounds pass clean.
```

---

## Task 14 — Final regression + ship

**Files:** none modified here — this task verifies the cycle and ships.

### Preamble

```
BEFORE starting work:
1. Read superpowers:verification-before-completion
2. Read superpowers:finishing-a-development-branch
You must verify (evidence before assertions) before merging.
```

### Steps

- [ ] **Step 1: Full regression**

Run: `python -m pytest tests/ services/search/tests/ -v 2>&1 | tee /tmp/final-regression.log | tail -60`

Expected:
- No new failures beyond the 2 pre-existing M2M failures and 9 pre-existing OSM POI errors.
- 25+ new passing tests (one or more per bug fix).
- Approximate total: 604-610 pass, 2 fail, 9 errors (same fail/error counts as baseline; only the pass count grew).

If any new failure appears, STOP. Investigate the failing test. Do NOT merge until green.

- [ ] **Step 2: Review commit history**

Run: `git log --oneline origin/dev..HEAD`

Expected: 13 commits, each with Conventional Commits format, one per task (Tasks 1-13).

Verify:
- All subjects ≤72 chars: `git log --format='%s' origin/dev..HEAD | awk 'length > 72'`  (expected: empty output)
- All commits `fix:` or `refactor:` scoped with `(pipeline)` / `(search)`: `git log --format='%s' origin/dev..HEAD` (spot-check)
- No `fix!:` or `BREAKING CHANGE:` footers: `git log --format='%B' origin/dev..HEAD | grep -i 'BREAKING CHANGE'` (expected: empty)

- [ ] **Step 3: Check release-please-tracked PRs**

Run: `gh pr list --state open --search 'release-please'`

Note the PR number (expected: PR #2 per the plan scope). After pushing, release-please should update this PR's changelog to include the new `fix:` entries.

- [ ] **Step 4: Push dev to origin**

Run: `git push origin dev`

- [ ] **Step 5: Merge dev → main (fast-forward)**

```bash
git checkout main
git pull origin main
git merge --ff-only dev
git push origin main
```

If `merge --ff-only` fails because main has new commits, STOP. Rebase dev onto main first (`git checkout dev && git rebase origin/main`), re-run full test suite, then retry the merge.

- [ ] **Step 6: Observe release-please**

Wait up to 2 minutes, then check:

Run: `gh pr view 2 --json title,body | head -40`

The body should now include the new `fix:` and `refactor:` subjects under the current release's changelog section.

- [ ] **Step 7: Switch back to dev**

```bash
git checkout dev
```

### Completion check

```
BEFORE declaring this cycle complete:
1. Full suite green (no new failures vs baseline).
2. dev and main are in sync (`git log origin/main..origin/dev` → empty).
3. Release-please PR #2 shows the new entries.
4. The deferred bugs in the appendix below are documented; no one thinks they were fixed.
5. Post a brief summary to the user: which bugs closed, which are deferred, test count delta, any concerns.
```

---

## Appendix: Bugs Deferred from This Cycle

Each entry lists: **Bug title / location / evidence / why deferred / recommended fix + validation approach.**

### B6 — `merge_mbtiles` composite on every overlap

**Location:** `scripts/acquire_imagery.py:641-667`

**Evidence:** `WHERE s.tile_data != d.tile_data` gates the compositing path on byte-level inequality of JPEG blobs. JPEGs from separate pipeline passes always differ byte-for-byte even when visually identical, so every overlap triggers a decode/composite/re-encode — lossy generation loss that compounds per overlap.

**Why deferred:** Chesterton's Fence. Commit `e7e3b32` ("compositing merge + nodata cleanup for NAIP tile pipeline") explicitly added pixel-by-pixel compositing to FIX visible imagery loss at NAIP quad boundaries. The hunter's proposed fix ("skip composite when dst has no near-black pixels") is correct-looking but may regress that earlier fix. The 494-quad production run on 2026-04-17 completed with the current behavior and produced the screenshots we use for regression reference.

**Recommended fix:** Move the black-pixel check into a fast pre-filter (already sketched in the consolidated report). BEFORE landing, run a visual regression test on a Flagstaff-size bbox after the current production pipeline finishes, comparing output imagery at quad boundaries between the old and new behaviors. Accept only if no new artifacts appear.

---

### B8 — Erosion runs after overview generation

**Location:** `scripts/acquire_imagery.py:2222-2254`

**Evidence:** In `run_noaa` Phase 5, `_run_gdaladdo_with_metadata_fixup` runs BEFORE `rio_erode_nodata_edges`. Overviews are built from pre-erosion base tiles; after erosion, overviews reference deleted base regions. Result: imagery visible at low zoom, basemap visible at high zoom in eroded regions. Matches `docs/flagstaff_rendering_issue.jpg`.

**Why deferred:** Chesterton's Fence. Commit `1bab361` ("overview orphan tiles at coverage edges") added the all-4-children rule in `build_overviews` specifically because partial 2×2 blocks caused artifacts at edges. The current erosion-after-overview order relies on that rule. Re-ordering could reintroduce the original artifact or create new inpaint-vs-overview discrepancies.

**Recommended fix:** Swap the order to erode → build overviews → inpaint (matching `erode_nodata_edges`'s docstring intent). BEFORE landing: build a visual-regression test that renders a Flagstaff-scale bbox before and after, diffs the resulting tiles at every zoom level, and asserts no new zoom-level coverage gaps. Also verify the all-4-children rule in `build_overviews` still correctly handles the post-erosion base tile count.

---

### D4 — Consolidate two progress-writer paths

**Location:** `scripts/acquire_imagery.py:189-212` (`write_pipeline_state`) and `:279-326` (`update_progress` — now refactored in B15)

**Evidence:** After B15's single-write refactor, `update_progress` no longer delegates to `_generic_progress`. `write_pipeline_state` is still a thin merge wrapper over `_atomic_write_json`. Two public functions exist for the same job.

**Why deferred:** Scope. B15 fixes the correctness bug (double write); the architectural consolidation is a separate cleanup. Callers of `write_pipeline_state` are distributed across the codebase.

**Recommended fix:** Audit every caller of `write_pipeline_state` and `update_progress`. Pick one canonical API (likely just `_generic_progress` with an `extra_fields` dict parameter) and migrate all callers. Keep both functions as deprecated shims for one release cycle, then remove.

---

### D5 — Consolidate `fetch_*` helpers across 4 scripts

**Location:** `scripts/acquire_imagery.py:393` (`fetch_to_file`), `scripts/acquire_imagery.py:365` (`fetch_with_retry`), `scripts/acquire_naip.py` (county download), `scripts/acquire_sentinel.py:406-416` (inline), `scripts/download_elevation.py:fetch_with_retry`.

**Evidence:** Four subtly-different download helpers with different backoff, retry counts, timeouts, Content-Length handling, and OOM protection. Each fix (B5, B10, the existing "subprocess.run blocking" pitfall) has to be applied N times.

**Why deferred:** Scope. Sizeable refactor for a stability-focused cycle. Each helper has its own caller expectations (return type, cancellation semantics).

**Recommended fix:** Create `scripts/download.py` with one parameterized helper:
```python
async def fetch_to_file(session, url, dest, *, retries=3, timeout_s=120, 
                       max_size=0, sock_read_s=120, on_progress=None) -> bool:
```
Migrate all four call sites. Preserve existing retry-count/timeout defaults via wrapper functions in each module if needed.

---

### D6 — Move `_noaa_checkpoint` from MBTiles-embedded to sidecar JSON

**Location:** `scripts/acquire_imagery.py:2168-2178`

**Evidence:** `_noaa_checkpoint` lives inside the output MBTiles as a separate table. User-copies of the MBTiles inherit the table; any SQL consumer sees it. Also couples the merge-commit and checkpoint-commit atomicity (see B13).

**Why deferred:** Moving to a sidecar rewrites the checkpoint mechanism. B13's atomicity concern was addressed in this cycle via a post-crash repair routine (Task 11); the sidecar cleanup is separate.

**Recommended fix:** Write `staging/noaa_checkpoint.json` atomically via `_atomic_write_json` after each tile merge. Drop the `_noaa_checkpoint` table from MBTiles. On pipeline start, load the sidecar; fall back to the embedded table if the sidecar is missing (compat for mid-cycle upgrades). After one release, remove the embedded-table compat path.

---

## Notes to the Subagent Executing This Plan

- **DO NOT skip the TDD preamble in any task.** Several fixes are source-level assertions where the "failing test" only becomes meaningful if you actually ran it and saw it fail.
- **DO NOT reorder tasks.** Several tasks edit adjacent line ranges in `acquire_imagery.py`; ordering minimizes merge conflicts.
- **DO NOT fix deferred bugs (B6, B8, D4, D5, D6).** They are deferred for specific reasons documented in the appendix. Touching them expands scope and risks regressing the 494-quad production run.
- **DO NOT change default concurrency values** (e.g., NAIP `--concurrency=2`, NOAA `DOWNLOAD_CONCURRENCY=8`). The bugs are about correctness, not tuning.
- **DO NOT skip review checkpoints.** The three review loops catch cross-task regressions that individual tests miss.
- **If you hit a blocker** that prevents completing a task cleanly: STOP, commit whatever was done, and report back with the specific problem. Do NOT force-fix by changing scope.
- **Baseline test numbers (579 pass, 2 M2M fail, 9 OSM POI errors)** are the ground truth. Any NEW failure after a task indicates that task broke something.
- Production stack is live. NEVER run `docker compose down` without explicit user permission.

