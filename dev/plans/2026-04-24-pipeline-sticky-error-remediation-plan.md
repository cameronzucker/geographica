# Pipeline sticky-error remediation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Worktrees are BANNED in this project per CLAUDE.md** — work directly on the main repo's branch (likely a new `fix/pipeline-sticky-error` branch off `dev`). Every commit must include the trailer `Agent: <your-moniker>` (each subagent picks one at session start; do not reuse `manzanita` across sessions).

**Goal:** Fix 17 confirmed bugs that cause the NOAA NAIP pipeline error state to appear sticky after a multi-state bbox failure, plus several orthogonal pipeline-state bugs surfaced during the bug hunt.

**Architecture:** Tackles 5 logical phases — (1) replace axis-aligned state-bbox intersection with true-polygon intersection using Census TIGER simplified boundaries; (2) harden server-side state management around `/admin/pipeline/{start,status,cancel}` plus add a new `/clear` endpoint; (3) fix NAIP/Sentinel state-file path mismatch; (4) clean up frontend stale-state bugs and surface dismissable errors; (5) integration-test the full retry path end-to-end.

**Tech stack:** Python 3.13 (FastAPI + Docker SDK + shapely 2.x), vanilla JS frontend (no framework), pytest with httpx-based integration tests in `services/search/tests/`, fixture data lives at `/srv/geographica/data/` (symlinked from `data/`).

**Frontend DOM safety:** All new and modified frontend code MUST use safe DOM patterns — `textContent` + `appendChild` for content, `replaceChildren()` for clearing, never `innerHTML` with any computed content. The existing codebase already follows this convention (e.g., `frontend/config/index.html:2779` deliberately uses textContent to prevent injection from backend error strings). The pre-commit security hook will reject any code that violates this.

---

## How to execute this plan

### Mandatory preamble for EVERY task

```
BEFORE starting work:
1. Invoke the superpowers:test-driven-development skill (read it; don't paraphrase from memory)
2. Read /home/administrator/Code/geographica/docs/pitfalls/testing-pitfalls.md
3. Read /home/administrator/Code/geographica/docs/pitfalls/implementation-pitfalls.md
4. Pre-flight assertion: `pwd && git rev-parse --abbrev-ref HEAD && git status --short`
   — confirm you are in /home/administrator/Code/geographica and on the right branch (NOT dev or main).
5. Pick a moniker (single word, lowercase, ctrl-F-friendly, plant/animal/geographic noun)
   and use it as `Agent: <moniker>` in every commit trailer this session.

Follow TDD strictly: write failing test → run to confirm failure → implement fix → run to confirm pass → commit.
```

### Mandatory completion check for EVERY task

```
BEFORE marking this task complete:
1. Re-read your tests against /home/administrator/Code/geographica/docs/pitfalls/testing-pitfalls.md.
   Specifically verify:
   - Tests assert observable behavior, not implementation detail
   - Negative paths are tested (the failure mode must fire)
   - Tests don't mock the layer the bug actually lives in
2. Run the full subset for the affected service:
   - For services/search/main.py changes: `cd services/search && python -m pytest -v`
   - For scripts/ changes: `python -m pytest tests/ -v`
   - For frontend/ changes: open frontend/config/ in a browser, exercise the affected flow manually, take a screenshot if the bug is visual
3. Run `git status --short` and confirm only intended files changed.
4. Verify post-commit branch state: `git log --oneline -1 && git branch --contains HEAD`
   — confirm the commit landed on the intended branch and includes your `Agent:` trailer.
```

### Mandatory review loop after every phase

```
After completing all tasks in a Phase:
You MUST carefully review the batch of work from multiple perspectives and revise/refine
as appropriate. Repeat this review loop (you must do a minimum of THREE review rounds;
if you still find substantive issues in the third review, keep going with additional
rounds until there are no findings) until you're confident there aren't any more issues.
Specifically check for:
- Cross-task naming consistency (function names, parameter names, error keys)
- Whether the test suite still passes end-to-end (`python -m pytest tests/ services/search/tests/ -v`)
- Whether the user-facing behavior matches each task's "Impact" claim
- Whether docs/pitfalls/ should be updated based on new patterns introduced

Then update your private journal and continue to the next phase.
```

### Test fixtures referenced throughout this plan

Several tasks reference fixtures that may not exist in `services/search/tests/conftest.py` yet. Before writing any test, **check the existing conftest** with:

```bash
cat services/search/tests/conftest.py
```

Add these fixtures to that file if not present (each is independent — add only what your task needs):

```python
# services/search/tests/conftest.py — additions

import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """Replace the search service's DATA_DIR with a tmp directory.
    Tests can write state files to this dir and verify behavior in
    isolation from production /srv/geographica/data/."""
    from services.search import main as search_main
    monkeypatch.setattr(search_main, "DATA_DIR", tmp_path)
    return tmp_path

@pytest.fixture
def client(tmp_data_dir):
    """Authed FastAPI test client. Auth is mocked so endpoints with
    Depends(require_config_source) work without setting headers."""
    from services.search.main import app, require_config_source
    app.dependency_overrides[require_config_source] = lambda: True
    yield TestClient(app)
    app.dependency_overrides.clear()

@pytest.fixture
def bare_client():
    """Unauth-ed client — for verifying that auth-gated endpoints reject."""
    from services.search.main import app
    return TestClient(app)

@pytest.fixture
def sample_noaa_body():
    return {
        "type": "imagery",
        "mode": "noaa",
        "state": "arizona",
        "bbox": "-114,32,-112,34",
        "concurrency": 4,
        "update": True,
    }

@pytest.fixture
def mock_docker_for_start():
    """Returns a MagicMock Docker client that lets /start proceed
    without actually spawning a container."""
    from unittest.mock import MagicMock
    import docker.errors
    mock = MagicMock()
    mock.containers.list.return_value = []  # no running pipeline
    mock.containers.get.side_effect = docker.errors.NotFound("none")
    mock.images.get.return_value = MagicMock()
    mock.containers.run.return_value = MagicMock(id="test-container-id")
    mock.networks.list.return_value = []
    return mock
```

If a fixture name in this plan doesn't match the existing conftest's convention, ALIGN to the existing convention rather than introduce a new name.

### Branch + commit convention

- Create a feature branch off `dev`: `git checkout -b fix/pipeline-sticky-error dev`
- Conventional Commits per [CONTRIBUTING.md](../../CONTRIBUTING.md). Types map:
  - `fix(search):` for `services/search/main.py` bugs
  - `fix(pipeline):` for `scripts/acquire_*.py` bugs
  - `fix(frontend):` for `frontend/config/index.html` bugs
  - `feat(search):` for the new `/clear` endpoint and `--state-file` plumbing
  - `feat(pipeline):` for the new polygon intersection function
  - `test(search):` / `test(pipeline):` for test-only commits
- Each commit message ends with the standard trailer block:
  ```
  Agent: <your-moniker>
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- Do NOT amend or rebase commits. Make new commits to fix follow-up issues.

---

## File structure

This plan touches:

| File | Tasks | Responsibility |
|---|---|---|
| `scripts/common/state_polygons.geojson` (NEW) | T1 | Census TIGER simplified state polygons, ~200 KB asset |
| `scripts/common/state_bboxes.py` | T2-T3 | Add `states_intersecting_polygon()`; keep AABB version for legacy callers |
| `scripts/common/tests/test_state_bboxes.py` (NEW) | T2 | TDD coverage for polygon intersection |
| `scripts/acquire_imagery.py` | T21 | Multi-state guard error message UX (after CB1 fix, this only fires for genuine cross-border bboxes) |
| `scripts/acquire_naip.py` | T15 | Accept `--state-file` argument |
| `scripts/acquire_sentinel.py` | T16 | Accept `--state-file` argument |
| `services/search/main.py` | T4-T14, T17 | All `/admin/pipeline/*` endpoint hardening + `/clear` endpoint + per-type state-file routing |
| `services/search/tests/test_pipeline_clear.py` (NEW) | T8 | TDD for /clear endpoint |
| `services/search/tests/test_pipeline_start_guards.py` (NEW) | T7 | TDD for /start multi-state guard |
| `services/search/tests/test_pipeline_status_writeback.py` (NEW) | T9 | TDD for /status writeback under lock |
| `services/search/tests/test_docker_error_propagation.py` (NEW) | T4, T5 | TDD for narrowed exception handling |
| `services/search/tests/test_pipeline_sticky_error_regression.py` (NEW) | T22 | End-to-end regression for the user's reported flow |
| `frontend/config/index.html` | T18-T21 | Stale-state invalidation, last-tab memory, dismiss button, error message UX |
| `docs/pitfalls/testing-pitfalls.md` | T23 | Append the 4 pitfall additions identified during the bug hunt |
| `dev/implementation-log.md` | T24 | Add an entry summarizing the remediation |

---

# Phase 1 — Polygon intersection (fixes CB1)

This phase replaces axis-aligned bbox intersection with true polygon intersection. Without this, every multi-state bbox false positive in the western US persists.

### Task 1: Acquire and bundle Census TIGER state polygons

**Files:**
- Create: `scripts/common/state_polygons.geojson` (~200 KB asset)

**Background:** The fix for CB1 needs polygon-accurate state boundaries. Census TIGER 2023 cb_2023_us_state_500k.shp simplified to GeoJSON satisfies all callers' accuracy needs. Bundling alongside `state_bboxes.py` (small reference asset, not tracked in `/srv/geographica/data/`) means both the search service and the pipeline container can reach it via the existing `./scripts:/scripts:ro` mount.

- [ ] **Step 1: Acquire the TIGER source**

```bash
# Run from /home/administrator/Code/geographica (host, not container — needs internet)
cd /tmp
wget https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip
unzip -o cb_2023_us_state_500k.zip
```

Expected: file `cb_2023_us_state_500k.shp` (and sidecar `.dbf`, `.prj`, `.shx`) in `/tmp/`.

- [ ] **Step 2: Convert + simplify to GeoJSON, filter to 48 contiguous states + DC**

```bash
# Requires ogr2ogr (gdal-bin). Verify: which ogr2ogr
ogr2ogr -f GeoJSON \
  -where "STUSPS NOT IN ('AK','HI','PR','VI','GU','AS','MP')" \
  -simplify 0.005 \
  -select "STUSPS,NAME" \
  /home/administrator/Code/geographica/scripts/common/state_polygons.geojson \
  /tmp/cb_2023_us_state_500k.shp
```

Expected: ~150-250 KB GeoJSON file. `STUSPS` (USPS code) and `NAME` properties retained; geometry simplified by ~0.005° (~500 m) which is precise enough for state-boundary intersection at typical user bbox scales.

- [ ] **Step 3: Verify file**

```bash
python3 -c "
import json
with open('scripts/common/state_polygons.geojson') as f:
    data = json.load(f)
features = data['features']
print(f'Features: {len(features)}')
codes = sorted(f['properties']['STUSPS'] for f in features)
print(f'Codes: {codes}')
assert len(features) == 49, f'Expected 49 (48 states + DC), got {len(features)}'
assert 'CA' in codes and 'NV' in codes and 'DC' in codes
print('OK')
"
```

Expected: `Features: 49` followed by `Codes: ['AL', 'AR', 'AZ', ..., 'WV', 'WY']` (49 codes total) followed by `OK`. If any assertion fails, Python raises AssertionError — re-acquire the file (Step 1) before retrying.

- [ ] **Step 4: Commit**

```bash
git add scripts/common/state_polygons.geojson
git commit -m "$(cat <<'EOF'
feat(pipeline): add Census TIGER simplified state polygons asset

200 KB GeoJSON of 48 CONUS states + DC, simplified to ~500m precision.
Replaces axis-aligned state bboxes for true-polygon intersection (CB1).

Source: census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip
Filtered: STUSPS NOT IN ('AK','HI','PR','VI','GU','AS','MP')
Simplified: ogr2ogr -simplify 0.005

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Add `states_intersecting_polygon()` with TDD

**Files:**
- Create: `scripts/common/tests/__init__.py` (empty, if not already present)
- Create: `scripts/common/tests/test_state_bboxes.py`
- Modify: `scripts/common/state_bboxes.py` — add new function, keep old `_states_intersecting` as an aliased back-compat shim

**Bug evidence:** [`scripts/common/state_bboxes.py:65-97`](../../scripts/common/state_bboxes.py#L65-L97). The `_states_intersecting` function uses axis-aligned state bboxes. California's rectangle `(-124.48, 32.53, -114.13, 42.01)` extends east to lon -114.13 at all latitudes, but at lat 36° CA's actual eastern border is around -119°. Result: a 0.1° bbox at Las Vegas `-115.15,36.10,-115.05,36.20` returns `[california, nevada]` despite touching zero CA land. Verified live during the bug hunt — see `dev/bug-hunts/2026-04-24-pipeline-sticky-error-consolidated.md` §CB1.

**Fix:** Add a new function that does polygon-polygon intersection using shapely + the GeoJSON from Task 1.

- [ ] **Step 1: Write the failing test**

Create `scripts/common/tests/test_state_bboxes.py`:

```python
"""Tests for state intersection.

These tests assert observable behavior (single-state bboxes return one state,
multi-state bboxes return multiple states) — they don't probe implementation.
The failing-mode is encoded explicitly: the user's Lake Mead bbox should NOT
return 'california' because CA has zero land in that region.
"""
import pytest
from scripts.common.state_bboxes import (
    states_intersecting,            # public alias, current AABB impl
    states_intersecting_polygon,    # new polygon impl (this PR)
)


# (bbox_str, expected_states_sorted, scenario_description)
CASES_SINGLE_STATE = [
    ("-115.6982,35.8829,-114.7706,36.5005", ["nevada"],
     "Lake Mead corner — touches NV/AZ rectangles but is fully in NV"),
    ("-115.15,36.10,-115.05,36.20", ["nevada"],
     "Las Vegas (0.1deg square) — fully in NV"),
    ("-119.5,39.1,-119.4,39.2", ["nevada"],
     "Reno area — east of CA's true border at this latitude"),
    ("-112.0,33.4,-111.9,33.5", ["arizona"],
     "Phoenix downtown — fully in AZ"),
    ("-111.9,40.7,-111.8,40.8", ["utah"],
     "Salt Lake City — fully in UT"),
]

CASES_MULTI_STATE = [
    # Bbox that genuinely straddles two states — Bullhead City AZ / Laughlin NV
    ("-114.62,35.13,-114.55,35.20", {"arizona", "nevada"},
     "Colorado River AZ/NV border — genuine multi-state"),
    # Four Corners
    ("-109.07,36.95,-109.03,37.05", {"arizona", "colorado", "new-mexico", "utah"},
     "Four Corners region"),
]


@pytest.mark.parametrize("bbox,expected,scenario", CASES_SINGLE_STATE)
def test_polygon_intersection_single_state(bbox, expected, scenario):
    result = sorted(states_intersecting_polygon(bbox))
    assert result == expected, f"{scenario}: got {result}, expected {expected}"


@pytest.mark.parametrize("bbox,expected_set,scenario", CASES_MULTI_STATE)
def test_polygon_intersection_multi_state(bbox, expected_set, scenario):
    result = set(states_intersecting_polygon(bbox))
    assert result == expected_set, f"{scenario}: got {result}, expected {expected_set}"


def test_polygon_intersection_malformed_bbox_returns_empty():
    assert states_intersecting_polygon("not,a,bbox") == []
    assert states_intersecting_polygon("") == []
    assert states_intersecting_polygon("1,2,3") == []  # only 3 parts


def test_polygon_intersection_outside_conus_returns_empty():
    # Atlantic Ocean
    assert states_intersecting_polygon("-50,30,-49,31") == []


def test_aabb_function_still_exists_for_back_compat():
    """The old _states_intersecting (and public alias) must remain importable
    for any caller we haven't migrated yet. Verify it's still callable and
    still uses AABB semantics (false-positive on Lake Mead)."""
    result = states_intersecting("-115.6982,35.8829,-114.7706,36.5005")
    # AABB false-positive expected — this is the bug we're fixing in callers,
    # not in this primitive.
    assert "california" in result, "AABB version should still false-positive on Lake Mead"
    assert "nevada" in result
```

- [ ] **Step 2: Run test to verify it fails with ImportError**

```bash
cd /home/administrator/Code/geographica
python -m pytest scripts/common/tests/test_state_bboxes.py -v
```

Expected: ImportError (or AttributeError) on `states_intersecting_polygon`.

- [ ] **Step 3: Implement `states_intersecting_polygon`**

Append to `scripts/common/state_bboxes.py`:

```python
# ---------------------------------------------------------------------------
# Polygon-accurate intersection (CB1 fix)
# ---------------------------------------------------------------------------

import json
from pathlib import Path
from functools import lru_cache

# Map USPS code -> NOAA slug. Single source of truth lives in main.py
# (SLUG_BY_USPS), but the pipeline container can't import from services/.
# Mirror it here. Keep alphabetized; add new entries when the catalog grows.
_USPS_TO_SLUG = {
    "AL": "alabama", "AZ": "arizona", "AR": "arkansas", "CA": "california",
    "CO": "colorado", "CT": "connecticut", "DE": "delaware",
    "DC": "district-of-columbia", "FL": "florida", "GA": "georgia-us",
    "ID": "idaho", "IL": "illinois", "IN": "indiana", "IA": "iowa",
    "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine",
    "MD": "maryland", "MA": "massachusetts", "MI": "michigan",
    "MN": "minnesota", "MS": "mississippi", "MO": "missouri",
    "MT": "montana", "NE": "nebraska", "NV": "nevada",
    "NH": "new-hampshire", "NJ": "new-jersey", "NM": "new-mexico",
    "NY": "new-york", "NC": "north-carolina", "ND": "north-dakota",
    "OH": "ohio", "OK": "oklahoma", "OR": "oregon", "PA": "pennsylvania",
    "RI": "rhode-island", "SC": "south-carolina", "SD": "south-dakota",
    "TN": "tennessee", "TX": "texas", "UT": "utah", "VT": "vermont",
    "VA": "virginia", "WA": "washington", "WV": "west-virginia",
    "WI": "wisconsin", "WY": "wyoming",
}


@lru_cache(maxsize=1)
def _load_state_polygons():
    """Load and cache (slug, polygon) pairs from the bundled GeoJSON.

    Lazy import of shapely so callers that don't need polygon math don't pay
    the import cost on module load.
    """
    from shapely.geometry import shape

    path = Path(__file__).parent / "state_polygons.geojson"
    with path.open() as fh:
        data = json.load(fh)

    pairs = []
    for feat in data["features"]:
        usps = feat["properties"]["STUSPS"]
        slug = _USPS_TO_SLUG.get(usps)
        if slug is None:
            continue
        pairs.append((slug, shape(feat["geometry"])))
    return pairs


def states_intersecting_polygon(bbox_str: str) -> list[str]:
    """Return slugs of states whose polygon truly intersects the given bbox.

    bbox_str is the Geographica-canonical "west,south,east,north" form.
    Returns an empty list for malformed input or bboxes outside CONUS+DC.
    Uses shapely + the bundled simplified Census TIGER 2023 polygons (see
    state_polygons.geojson). Replaces _states_intersecting's AABB-only
    semantics for callers that need geographic accuracy.

    Order of returned list matches the GeoJSON's feature order, which mirrors
    Census USPS-alphabetical, so callers that need stable ordering get it
    for free.
    """
    from shapely.geometry import box

    try:
        parts = [p.strip() for p in bbox_str.split(",")]
        if len(parts) != 4:
            return []
        w, s, e, n = (float(x) for x in parts)
    except (ValueError, AttributeError):
        return []

    user_box = box(w, s, e, n)
    matching = []
    for slug, poly in _load_state_polygons():
        if poly.intersects(user_box):
            matching.append(slug)
    return matching
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest scripts/common/tests/test_state_bboxes.py -v
```

Expected: All cases PASS, including the formerly-failing Lake Mead and Las Vegas single-state checks.

- [ ] **Step 5: Verify shapely is actually available in both contexts**

```bash
# Host context (search service)
python3 -c "import shapely; print(shapely.__version__)"
# Pipeline container context
docker run --rm -v $(pwd)/scripts:/scripts:ro geographica-pipeline \
  python3 -c "import shapely; print(shapely.__version__)"
```

Expected: shapely 2.x reported in both. If pipeline container fails, add `shapely` to `services/pipeline/requirements.txt` (or wherever the container's deps are pinned) and rebuild before proceeding.

- [ ] **Step 6: Commit**

```bash
git add scripts/common/state_bboxes.py scripts/common/tests/
git commit -m "$(cat <<'EOF'
feat(pipeline): polygon-accurate state intersection

Adds states_intersecting_polygon() using shapely + bundled Census TIGER
2023 simplified polygons. Replaces axis-aligned bbox intersection for
callers that need geographic accuracy.

Fixes the underlying primitive for CB1 — callers migrated in T3.

Refs: dev/bug-hunts/2026-04-24-pipeline-sticky-error-consolidated.md

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Migrate callers from AABB to polygon intersection

**Files:**
- Modify: `services/search/main.py:1242` (inside `_noaa_peak_and_snapshot`)
- Modify: `services/search/main.py:2095` (inside `noaa_estimate`)
- Modify: `scripts/acquire_imagery.py:153` and L2229 area (inside `resolve_noaa_candidates`)
- Modify: `services/search/main.py:1944-1948` (`_count_noaa_tiles` area-ratio calc — verify if it should also migrate; document the decision)

**Background:** Three call sites use the AABB function today; all three want polygon accuracy. Keep the AABB function importable (Task 2 keeps it) for any future caller that genuinely wants the loose check (none currently exist).

- [ ] **Step 1: Identify every caller**

```bash
cd /home/administrator/Code/geographica
grep -rn 'states_intersecting\|_states_intersecting' --include='*.py' \
  services/ scripts/ tests/ | grep -v 'test_state_bboxes'
```

Expected output should match these locations (verify exactly before editing):
- services/search/main.py — 2 call sites (NOAA peak/snapshot, noaa_estimate, possibly _count_noaa_tiles)
- scripts/acquire_imagery.py — 1-2 call sites in `resolve_noaa_candidates`

- [ ] **Step 2: Write a failing integration test (regression test for the user's bug)**

Add to `services/search/tests/test_noaa_estimate.py` (check existing tests first to match fixture style):

```python
def test_lake_mead_bbox_resolves_to_single_state(client):
    """Regression for CB1: a bbox in southern NV that touches no CA land
    must NOT be classified as multi-state."""
    resp = client.get("/admin/pipeline/noaa/estimate?bbox=-115.6982,35.8829,-114.7706,36.5005")
    assert resp.status_code == 200
    data = resp.json()
    # The estimate endpoint returns a per-state breakdown.
    # Adapt this assertion to whatever shape the endpoint actually returns
    # — the key invariant is "california is NOT in the response."
    states = data.get("states") or list((data.get("per_state") or {}).keys())
    assert "california" not in states, f"got states={states}"
    assert "nevada" in states, f"got states={states}"
```

- [ ] **Step 3: Run test, expect failure**

```bash
cd services/search && python -m pytest tests/test_noaa_estimate.py -v -k lake_mead
```

Expected: FAIL with "california" in the response (because the AABB version is still in play upstream).

- [ ] **Step 4: Replace each call site**

For each of the call sites identified in Step 1:

```python
# Before
from scripts.common.state_bboxes import states_intersecting
intersecting = states_intersecting(body.bbox)

# After
from scripts.common.state_bboxes import states_intersecting_polygon
intersecting = states_intersecting_polygon(body.bbox)
```

Notes:
- `_count_noaa_tiles` at main.py:1944-1948 is an area-ratio calc, not an intersection check. Read the function carefully. If it's computing "what fraction of state X does the user's bbox cover," it likely uses AABB intersection-area math. Migrating it to polygon math is a BIGGER change — for this plan, keep the AABB area calc, but add a code comment noting the inconsistency. Document this decision in the commit message.

- [ ] **Step 5: Run regression test, expect pass**

```bash
cd services/search && python -m pytest tests/test_noaa_estimate.py -v -k lake_mead
```

Expected: PASS. CA correctly excluded.

- [ ] **Step 6: Run full test suite**

```bash
cd /home/administrator/Code/geographica
python -m pytest tests/ services/search/tests/ -v
```

Expected: All pass. If any test breaks, investigate — it may be relying on AABB false-positives.

- [ ] **Step 7: Commit**

```bash
git add services/search/main.py scripts/acquire_imagery.py services/search/tests/test_noaa_estimate.py
git commit -m "$(cat <<'EOF'
fix(search): migrate state-intersection callers to polygon math

Replaces axis-aligned bbox intersection at three call sites:
- _noaa_peak_and_snapshot (main.py:1242)
- noaa_estimate (main.py:2095)
- resolve_noaa_candidates (acquire_imagery.py L153/L2229)

Adds regression test: Lake Mead bbox now correctly returns [nevada], not
[arizona, california, nevada]. Closes the underlying classification bug
that made the multi-state guardrail trip on every southern-NV bbox.

NOT MIGRATED: _count_noaa_tiles area-ratio calc (still uses AABB area
math, documented inline). Migrating that is a bigger change deferred
to a future plan since it requires re-deriving the area-ratio model.

Closes: CB1

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 1 review checkpoint

After Tasks 1-3, run the **mandatory review loop** (3+ rounds, see preamble). Specifically check:
- [ ] Lake Mead bbox returns single-state at the live `/admin/pipeline/noaa/estimate` endpoint (curl test)
- [ ] No test regressions in `python -m pytest tests/ services/search/tests/ -v`
- [ ] Pipeline container can import shapely (verified in T2 step 5)
- [ ] No commits mention worktrees, no destructive git ops invoked

---

# Phase 2 — Server hardening

This phase fixes 12 bugs in `services/search/main.py`. Tasks T4-T14 must execute SERIALLY because they touch the same file. Each subagent picks up from the previous task's commit.

### Task 4: Narrow exception in stale-container removal (CB4)

**File:** `services/search/main.py:1582-1587`

**Bug evidence:** Bare `except: pass` swallows all Docker errors during stale-container cleanup. If `remove(force=True)` silently fails, `containers.run()` at L1590 hits a name-conflict, raising a generic exception that re-raises as HTTP 500. The state-file write at L1617 never runs, preserving the prior error state.

- [ ] **Step 1: Write failing test**

Create `services/search/tests/test_docker_error_propagation.py`:

```python
"""Tests for narrowed Docker exception handling at the /start path."""
import pytest
from unittest.mock import MagicMock, patch
import docker.errors


def test_start_pipeline_surfaces_remove_error_when_not_notfound(client, sample_noaa_body):
    """If old.remove() raises something other than NotFound, the /start
    handler must NOT silently continue — it must return a 5xx so the user
    knows something went wrong."""
    mock_old = MagicMock()
    mock_old.remove.side_effect = docker.errors.APIError("Permission denied")
    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_old
    mock_client.images.get.return_value = MagicMock()

    with patch("services.search.main._get_docker_client", return_value=mock_client):
        resp = client.post("/admin/pipeline/start", json=sample_noaa_body)

    assert resp.status_code in (500, 503), f"got {resp.status_code}, body: {resp.text}"
    # Raw Docker exception strings must NOT leak verbatim
    assert "Permission denied" not in resp.text or "permission" in resp.text.lower(), \
        "raw exception string should be wrapped, not leaked"


def test_start_pipeline_continues_when_no_stale_container(client, sample_noaa_body):
    """If old container doesn't exist (NotFound), /start should proceed
    normally."""
    mock_client = MagicMock()
    mock_client.containers.get.side_effect = docker.errors.NotFound("no such container")
    mock_client.images.get.return_value = MagicMock()
    mock_client.containers.run.return_value = MagicMock(id="abc123")

    with patch("services.search.main._get_docker_client", return_value=mock_client):
        resp = client.post("/admin/pipeline/start", json=sample_noaa_body)

    # Either 200 (if all other gates pass) or a sensible 4xx — but NOT 500
    assert resp.status_code != 500, f"got 500: {resp.text}"
```

Add a `sample_noaa_body` fixture to `services/search/tests/conftest.py` if not already present:

```python
@pytest.fixture
def sample_noaa_body():
    return {
        "type": "imagery",
        "mode": "noaa",
        "state": "arizona",
        "bbox": "-114,32,-112,34",
        "concurrency": 4,
        "update": True,
    }
```

- [ ] **Step 2: Run test, expect failure**

```bash
cd services/search && python -m pytest tests/test_docker_error_propagation.py::test_start_pipeline_surfaces_remove_error_when_not_notfound -v
```

Expected: FAIL — currently the bare `except: pass` swallows the error.

- [ ] **Step 3: Narrow the except**

Edit `services/search/main.py:1582-1587`:

```python
# Before
try:
    old = client.containers.get("geographica-pipeline")
    old.remove(force=True)
except Exception:
    pass

# After
try:
    old = client.containers.get("geographica-pipeline")
    old.remove(force=True)
except docker.errors.NotFound:
    # No stale container — fine, proceed.
    pass
except docker.errors.APIError as e:
    log.error("Failed to remove stale pipeline container: %s", e)
    raise HTTPException(
        status_code=503,
        detail={
            "status": "docker_unavailable",
            "message": "Could not clean up prior pipeline container.",
            "hint": "Try again in a moment, or run 'docker rm -f geographica-pipeline' manually.",
        },
    )
```

Verify the import: `import docker.errors` at the top of main.py. If absent, add it next to the existing `import docker`.

- [ ] **Step 4: Run test, expect pass**

```bash
cd services/search && python -m pytest tests/test_docker_error_propagation.py -v
```

Expected: both tests pass.

- [ ] **Step 5: Run full search suite**

```bash
cd services/search && python -m pytest -v
```

Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add services/search/main.py services/search/tests/
git commit -m "$(cat <<'EOF'
fix(search): narrow exception handling on stale-container removal

Bare 'except: pass' at L1582 swallowed all Docker errors during cleanup.
If remove(force=True) silently failed, the subsequent containers.run()
hit a name-conflict and the user saw HTTP 500 with the prior error
state preserved verbatim.

Now: only NotFound is silently OK; APIError surfaces as a structured
503 so the user knows what went wrong.

Closes: CB4

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Narrow exception in `_is_pipeline_container_running` (CB9)

**File:** `services/search/main.py:1175-1187`

**Bug evidence:** Bare except returns False on any Docker error. The /start 409 gate at L1396 evaluates "no pipeline running" during any Docker hiccup — so two simultaneous /start requests during a daemon restart can both pass the gate.

- [ ] **Step 1: Write failing test**

Add to `services/search/tests/test_docker_error_propagation.py`:

```python
def test_is_pipeline_running_returns_unknown_on_docker_error():
    """The function must NOT return False (which means 'safe to start') on
    arbitrary Docker errors — that creates a false-negative gate."""
    from services.search.main import _is_pipeline_container_running

    mock_client = MagicMock()
    mock_client.containers.list.side_effect = docker.errors.APIError("daemon offline")

    # New contract: returns "unknown" on error, callers must treat as "running"
    result = _is_pipeline_container_running(mock_client)
    assert result == "unknown", f"got {result!r}"


def test_is_pipeline_running_returns_running_when_container_running():
    from services.search.main import _is_pipeline_container_running
    mock_container = MagicMock(status="running")
    mock_client = MagicMock()
    mock_client.containers.list.return_value = [mock_container]
    assert _is_pipeline_container_running(mock_client) == "running"


def test_is_pipeline_running_returns_not_running_when_no_containers():
    from services.search.main import _is_pipeline_container_running
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    assert _is_pipeline_container_running(mock_client) == "not_running"
```

- [ ] **Step 2: Run test, expect failure** (function still returns bool)

- [ ] **Step 3: Implement**

Edit `services/search/main.py:1175-1187`:

```python
from typing import Literal

def _is_pipeline_container_running(client) -> Literal["running", "not_running", "unknown"]:
    """Check if any pipeline container is currently running.

    Matches both admin-started containers (geographica-pipeline) and
    CLI-started ones (geographica-pipeline-run-*).

    Returns:
        "running"     — at least one container with status == "running"
        "not_running" — query succeeded, no running container found
        "unknown"     — Docker query failed; callers must treat as "running"
                        (fail closed) to avoid spawning duplicate pipelines.
    """
    try:
        containers = client.containers.list(
            all=False, filters={"name": "geographica-pipeline"}
        )
    except docker.errors.DockerException:
        return "unknown"

    return "running" if any(c.status == "running" for c in containers) else "not_running"
```

Update all callers (search for `_is_pipeline_container_running(`):

```python
# Before (at L1396 and L1404)
if _is_pipeline_container_running(client):
    raise HTTPException(...)

# After
status = _is_pipeline_container_running(client)
if status == "running":
    raise HTTPException(status_code=409, detail="A pipeline job is already running")
elif status == "unknown":
    raise HTTPException(
        status_code=503,
        detail={
            "status": "docker_unavailable",
            "message": "Cannot determine pipeline state — Docker daemon not responding",
            "hint": "Try again in a moment.",
        },
    )
# status == "not_running": proceed
```

Find every other caller and update similarly.

- [ ] **Step 4: Run tests, expect pass**

```bash
cd services/search && python -m pytest tests/test_docker_error_propagation.py -v
cd services/search && python -m pytest -v  # full suite
```

Expected: new tests pass, no regressions.

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/test_docker_error_propagation.py
git commit -m "$(cat <<'EOF'
fix(search): _is_pipeline_container_running returns 3-state result

Was: bare except returned False on any Docker error, creating a
false-negative gate where two concurrent /start calls could both
spawn pipelines during a daemon hiccup.

Now: returns 'running' / 'not_running' / 'unknown'. Callers treat
'unknown' as 'fail closed' (return 503). DockerException is the
only caught class — programming errors propagate normally.

Closes: CB9

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Atomic state-file write at /start (CB8)

**File:** `services/search/main.py:1617`

**Bug evidence:** /start uses `state_file.write_text(...)` (truncate-in-place); every other writer uses tmp+rename. Concurrent readers can see torn JSON.

- [ ] **Step 1: Extract a shared helper, then test it**

Create `services/search/_state_io.py`:

```python
"""Atomic JSON writer for pipeline state files.

Used by /start, /cancel, /status, and /clear handlers — anywhere a writer
needs to atomically replace a state file that other processes may be
reading concurrently.
"""
import json
import os
from pathlib import Path


def atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON to ``path`` via tmp + os.replace (atomic on POSIX).

    Reader processes will either see the prior file contents or the new
    file contents — never a torn write.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp), str(path))
```

Create `services/search/tests/test_state_io.py`:

```python
import threading
import json
import time
from services.search._state_io import atomic_write_json


def test_atomic_write_no_torn_reads(tmp_path):
    """Concurrent reader sees either old or new contents, never torn JSON."""
    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({"status": "completed"}))

    errors = []

    def reader_loop():
        for _ in range(2000):
            try:
                json.loads(state_file.read_text())
            except json.JSONDecodeError as e:
                errors.append(e)
            time.sleep(0.0001)

    def writer_loop():
        for i in range(200):
            atomic_write_json(state_file, {"status": "running", "iter": i})
            time.sleep(0.0005)

    t_read = threading.Thread(target=reader_loop)
    t_write = threading.Thread(target=writer_loop)
    t_read.start(); t_write.start()
    t_read.join(); t_write.join()

    assert errors == [], f"{len(errors)} torn-JSON reads observed"
```

- [ ] **Step 2: Run, expect pass** (helper itself is straightforward)

- [ ] **Step 3: Replace the non-atomic write at L1617**

```python
# Before
state_file.write_text(json.dumps(state_data, indent=2))

# After
from services.search._state_io import atomic_write_json
atomic_write_json(state_file, state_data)
```

Apply the same swap to any other non-atomic state writes in main.py (grep for `state_file.write_text`).

- [ ] **Step 4: Run full suite, expect pass**

```bash
cd services/search && python -m pytest -v
```

- [ ] **Step 5: Commit**

```bash
git add services/search/_state_io.py services/search/main.py services/search/tests/test_state_io.py
git commit -m "$(cat <<'EOF'
fix(search): atomic state-file write at /start

Replaces non-atomic write_text() with shared atomic_write_json helper.
/start was the only writer in the project not using atomic writes;
readers occasionally saw torn JSON during a Start.

New module: services/search/_state_io.py
Threading torture test covering concurrent reader+writer.

Closes: CB8

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: /start multi-state guard returns structured 409 (CB2)

**File:** `services/search/main.py:1336-1385`

**Bug evidence:** The /start endpoint already calls `states_intersecting_polygon` (after Task 3) inside `_noaa_peak_and_snapshot`, but discards the count. Multi-state requests get dispatched to a doomed container.

- [ ] **Step 1: Write failing test**

Create `services/search/tests/test_pipeline_start_guards.py`:

```python
def test_start_pipeline_rejects_multi_state_bbox(client):
    """A bbox that spans 2+ cataloged states must be rejected with 409
    BEFORE a container is dispatched."""
    # Bullhead City AZ / Laughlin NV — genuine border crossing
    body = {
        "type": "imagery",
        "mode": "noaa",
        "bbox": "-114.62,35.13,-114.55,35.20",
        "acknowledge_missing": True,  # so we don't hit the missing-state gate
    }
    resp = client.post("/admin/pipeline/start", json=body)
    assert resp.status_code == 409, f"got {resp.status_code}: {resp.text}"
    detail = resp.json().get("detail", {})
    assert detail.get("status") == "multi_state_unsupported"
    assert "states" in detail
    assert set(detail["states"]) == {"arizona", "nevada"}


def test_start_pipeline_accepts_single_state_bbox(client, mock_docker_for_start):
    """A bbox fully within one state must NOT trigger multi-state rejection."""
    body = {
        "type": "imagery",
        "mode": "noaa",
        "bbox": "-115.6982,35.8829,-114.7706,36.5005",  # Lake Mead, NV-only after CB1
    }
    resp = client.post("/admin/pipeline/start", json=body)
    # Either 200 (all gates pass) or 503 (mocked Docker failure) — NOT 409 with multi_state
    if resp.status_code == 409:
        detail = resp.json().get("detail", {})
        assert detail.get("status") != "multi_state_unsupported"
```

- [ ] **Step 2: Run test, expect failure** (no multi-state guard yet)

- [ ] **Step 3: Add the guard at /start**

Insert immediately after `_noaa_peak_and_snapshot` returns (the section that already handles `missing` and `peak_required_gb`), before the lock acquisition (around L1386):

```python
# After _noaa_peak_and_snapshot returns (missing, peak_required_gb, snapshot_path)
# and after the missing-state and peak-disk gates.
if is_noaa and body.bbox and not body.state:
    # Pre-flight multi-state check. The pipeline script will hard-exit if
    # >1 cataloged state intersects the bbox (multi-state dispatch is
    # unimplemented; tracked as deferred work). Surface this synchronously
    # rather than dispatching a container that crashes within a second.
    from scripts.common.state_bboxes import states_intersecting_polygon

    # DECISION: load the catalog inline here rather than refactoring
    # _noaa_peak_and_snapshot to return entries. Reason: that function's
    # 3-tuple return shape is referenced by other callers and tests; a
    # signature change would cascade. The catalog is small (one JSON read
    # of ~30 KB) so the duplicate load is cheap.
    catalog, _ = _load_noaa_catalog(DATA_DIR)
    catalog_entries = catalog.get("entries", {}) if catalog else {}

    intersecting = states_intersecting_polygon(body.bbox)
    cataloged = [s for s in intersecting if s in catalog_entries]

    if len(cataloged) > 1:
        raise HTTPException(
            status_code=409,
            detail={
                "status": "multi_state_unsupported",
                "states": cataloged,
                "message": (
                    f"This bbox intersects {len(cataloged)} cataloged states "
                    f"({', '.join(s.upper() for s in cataloged)}). Multi-state "
                    "dispatch is not yet implemented. Either narrow the bbox to "
                    "fit one state, or use the 'Whole state' tab to dispatch "
                    "one state at a time."
                ),
                "suggested_states": cataloged,
            },
        )
```

- [ ] **Step 4: Run tests, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/test_pipeline_start_guards.py
git commit -m "$(cat <<'EOF'
fix(search): /start rejects multi-state bbox synchronously

Was: multi-state bbox dispatched a doomed pipeline container that
crashed with status=error within ~1s. User saw flickering state
and the same error message regardless of bbox.

Now: /start returns 409 with structured detail (status, states,
suggested_states, human-readable message). No container spawned.

Closes: CB2

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: New `POST /admin/pipeline/clear` endpoint (CB3 server side)

**File:** `services/search/main.py` (add new handler near /cancel at L1784)

**Bug evidence:** No path clears `status: "error"` from the state file. /cancel only handles "running"; no other endpoint exists.

- [ ] **Step 1: Write failing test**

Create `services/search/tests/test_pipeline_clear.py`:

```python
import json
from unittest.mock import MagicMock, patch


def test_clear_endpoint_removes_error_state(client, tmp_data_dir):
    """POST /admin/pipeline/clear must reset an errored state file."""
    state_file = tmp_data_dir / ".pipeline-state.json"
    state_file.write_text(json.dumps({
        "status": "error",
        "type": "imagery",
        "error": "some prior error",
    }))
    resp = client.post("/admin/pipeline/clear?type=imagery")
    assert resp.status_code == 200
    state = json.loads(state_file.read_text())
    assert state == {} or state.get("status") in (None, "idle"), \
        f"state should be reset, got {state}"


def test_clear_endpoint_refuses_when_running(client, tmp_data_dir):
    """Refuse to clear if status is 'running' AND a real container exists."""
    state_file = tmp_data_dir / ".pipeline-state.json"
    state_file.write_text(json.dumps({
        "status": "running",
        "type": "imagery",
        "container_id": "abc",
    }))
    mock_client = MagicMock()
    mock_container = MagicMock(status="running")
    mock_client.containers.list.return_value = [mock_container]
    with patch("services.search.main._get_docker_client", return_value=mock_client):
        resp = client.post("/admin/pipeline/clear?type=imagery")
    assert resp.status_code == 409
    state = json.loads(state_file.read_text())
    assert state.get("status") == "running"  # unchanged


def test_clear_endpoint_clears_running_state_when_container_gone(client, tmp_data_dir):
    """If state says 'running' but no container exists, treat as stale and clear."""
    state_file = tmp_data_dir / ".pipeline-state.json"
    state_file.write_text(json.dumps({"status": "running", "type": "imagery"}))
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []
    with patch("services.search.main._get_docker_client", return_value=mock_client):
        resp = client.post("/admin/pipeline/clear?type=imagery")
    assert resp.status_code == 200


def test_clear_endpoint_idempotent_when_no_state_file(client, tmp_data_dir):
    """No state file = nothing to clear, return 200."""
    resp = client.post("/admin/pipeline/clear?type=imagery")
    assert resp.status_code == 200


def test_clear_endpoint_requires_auth(bare_client):
    """Without config-source header, /clear must reject."""
    resp = bare_client.post("/admin/pipeline/clear?type=imagery")
    assert resp.status_code in (401, 403)
```

- [ ] **Step 2: Run test, expect failure** (no endpoint yet)

- [ ] **Step 3: Implement endpoint**

Add to `services/search/main.py` near /cancel:

```python
@app.post("/admin/pipeline/clear", dependencies=[Depends(require_config_source)])
async def pipeline_clear(type: str = Query("imagery", description="Pipeline type")):
    """Clear a pipeline state file. Refuses to clear if a real container is running.

    Idempotent: safe to call when no state file exists or when state is already idle.
    """
    if type not in ("imagery", "elevation", "osm_poi", "sentinel", "naip", "import"):
        raise HTTPException(status_code=422, detail="Invalid type")

    async with _pipeline_lock:
        state_file = _state_file_for_type(type)
        if not state_file.exists():
            return {"status": "cleared"}

        try:
            state_data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            state_data = {}

        current_status = state_data.get("status")
        if current_status in ("running", "cancelling"):
            # Verify the container actually exists before refusing — if it
            # doesn't, the state file is stale and clearable.
            client = _get_docker_client()
            try:
                container_state = _is_pipeline_container_running(client) if client else "unknown"
            finally:
                if client:
                    client.close()

            if container_state == "running":
                raise HTTPException(
                    status_code=409,
                    detail={
                        "status": "pipeline_running",
                        "message": f"Cannot clear: pipeline status is '{current_status}'. Cancel it first.",
                    },
                )
            # DECISION: container_state == "unknown" (Docker unreachable)
            # falls through to clear-the-stale-state. Reason: refusing to
            # clear when Docker is also broken creates a worse stickiness
            # (user is now blocked by TWO problems). The trade-off is that
            # if Docker comes back and a container WAS running, we clobber
            # its state file — but the running container will overwrite
            # state on its next update_progress call (~1s).
            # container_state == "not_running": stale state, safe to clear.

        # Atomic clear via shared helper from T6
        from services.search._state_io import atomic_write_json
        atomic_write_json(state_file, {})

    return {"status": "cleared"}
```

- [ ] **Step 4: Run tests, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/test_pipeline_clear.py
git commit -m "$(cat <<'EOF'
feat(search): /admin/pipeline/clear endpoint

Lets the UI dismiss a sticky error state. Refuses to clear while a
real container is running (verifies via Docker, not just state file).

Idempotent and atomic. Auth-gated like /start.

Closes: CB3 (server side; frontend Dismiss button in T20)

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: /status writeback under `_pipeline_lock` (CB11)

**File:** `services/search/main.py:1631-1764`

**Bug evidence:** /status performs reconciliation writebacks without holding `_pipeline_lock`, racing with /start's writes.

- [ ] **Step 1: Write failing test**

Create `services/search/tests/test_pipeline_status_writeback.py`:

```python
import asyncio
import json
import pytest


def test_status_writeback_re_reads_under_lock(tmp_path, monkeypatch):
    """The /status writeback path must re-read the state file under the
    lock and skip the writeback if another writer (e.g. /start) has
    landed in between. Direct unit test of the helper, not the endpoint.

    Strategy: extract the writeback decision into a function
    `_status_reconcile_and_write(state_file, observed_state, new_state)`
    that:
      1. Acquires _pipeline_lock
      2. Re-reads state_file
      3. If current.started_at == observed_state.started_at: write new_state
         else: skip (another writer landed)

    This test verifies (3) — when the file changed under us, no overwrite.
    """
    import asyncio
    from services.search import main as search_main

    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({"status": "running", "started_at": "T2", "type": "imagery"}))

    # Caller observed an older snapshot
    observed_state = {"status": "completed", "started_at": "T1", "type": "imagery"}
    new_state = {"status": "interrupted", "started_at": "T1", "type": "imagery"}

    async def run():
        await search_main._status_reconcile_and_write(state_file, observed_state, new_state)

    asyncio.run(run())

    # State file should NOT be overwritten because started_at didn't match
    final = json.loads(state_file.read_text())
    assert final["status"] == "running"
    assert final["started_at"] == "T2"


def test_status_writeback_writes_when_unchanged(tmp_path):
    """When the file matches the observed state, writeback proceeds."""
    import asyncio
    from services.search import main as search_main

    state_file = tmp_path / ".pipeline-state.json"
    state_file.write_text(json.dumps({"status": "running", "started_at": "T1", "type": "imagery"}))

    observed_state = {"status": "running", "started_at": "T1", "type": "imagery"}
    new_state = {"status": "completed", "started_at": "T1", "type": "imagery"}

    async def run():
        await search_main._status_reconcile_and_write(state_file, observed_state, new_state)

    asyncio.run(run())

    final = json.loads(state_file.read_text())
    assert final["status"] == "completed"
```

(The exact mocking strategy depends on the existing test infrastructure. Read `services/search/tests/test_pipeline_status_m2m.py` for patterns.)

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Extract a writeback helper, call it from /status**

Add to `services/search/main.py`:

```python
async def _status_reconcile_and_write(
    state_file: Path,
    observed_state: dict,
    new_state: dict,
) -> bool:
    """Atomically write new_state to state_file if-and-only-if the file
    still matches what the caller observed. Returns True on write, False
    on skip-due-to-conflict.

    Uses _pipeline_lock + an inside-the-lock re-read to avoid TOCTOU
    against /start, /cancel, /clear, and the pipeline container's own
    update_progress writes.

    Match key is `started_at` — every fresh /start writes a new ISO
    timestamp, so a mismatch means another writer landed between the
    caller's read and this writeback.
    """
    from services.search._state_io import atomic_write_json
    async with _pipeline_lock:
        try:
            current = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            current = {}
        if current.get("started_at") != observed_state.get("started_at"):
            # Another writer landed; skip writeback to avoid clobbering.
            return False
        atomic_write_json(state_file, new_state)
        return True
```

In `pipeline_status`, replace the existing writeback block:

```python
# Identify the writeback block — search for the pattern where /status
# decides to update state_data and currently calls write_text/atomic_write_json.
# Replace with:
new_state = reconcile(state_data, container_running)
if new_state != state_data:
    await _status_reconcile_and_write(state_file, state_data, new_state)
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/test_pipeline_status_writeback.py
git commit -m "$(cat <<'EOF'
fix(search): /status reconciliation writeback under lock

Was: /status writebacks race with /start writes — a status poll that
started before /start could clobber the fresh running state.

Now: read-modify-write portion holds _pipeline_lock and re-reads
under the lock to avoid TOCTOU. Read-only path is unchanged
(no lock contention on the common case).

Closes: CB11

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: /status auth (CB15)

**File:** `services/search/main.py:1631`

**Bug evidence:** /status performs privileged side effects (TileServer restart, MBTiles WAL checkpoint) but has no `Depends(require_config_source)`.

- [ ] **Step 1: Write failing test**

Add to existing pipeline-status test:

```python
def test_status_requires_auth(bare_client):
    """/status performs privileged side effects (TileServer restart,
    MBTiles checkpoint) and must require config-source auth."""
    resp = bare_client.get("/admin/pipeline/status?type=imagery")
    assert resp.status_code in (401, 403), f"got {resp.status_code}"
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Add auth dependency**

```python
# Before
@app.get("/admin/pipeline/status")
async def pipeline_status(...):

# After
@app.get("/admin/pipeline/status", dependencies=[Depends(require_config_source)])
async def pipeline_status(...):
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Verify frontend still works**

Open `frontend/config/index.html` in a browser and confirm /status calls succeed. The frontend's `cfgFetch` helper should already attach the auth header — verify in DevTools Network tab.

- [ ] **Step 6: Commit**

```bash
git add services/search/main.py services/search/tests/
git commit -m "$(cat <<'EOF'
fix(search): require auth on /admin/pipeline/status

The endpoint performs privileged side effects (TileServer restart,
MBTiles WAL checkpoint) that an unauthed caller could trigger.

Frontend cfgFetch already sends the required header, so no frontend
change.

Closes: CB15

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: /status surfaces structured errors instead of "unknown" (CB17)

**File:** `services/search/main.py:1642-1643`

**Bug evidence:** `except (json.JSONDecodeError, OSError)` masks permission and disk-full errors as `"status": "unknown"`. Frontend renders empty.

- [ ] **Step 1: Write failing test**

```python
def test_status_surfaces_permission_error(client, tmp_data_dir):
    """When state file is unreadable due to permissions, /status must
    surface a useful error message, not 'unknown'."""
    state_file = tmp_data_dir / ".pipeline-state.json"
    state_file.write_text('{"status": "completed"}')
    state_file.chmod(0o000)
    try:
        resp = client.get("/admin/pipeline/status?type=imagery")
        assert resp.status_code == 200  # endpoint still responds
        data = resp.json()
        assert data.get("status") == "error"
        err = data.get("error", "").lower()
        assert "permission" in err or "could not read" in err or "unreadable" in err
    finally:
        state_file.chmod(0o644)
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Refine error handling**

```python
# Before
state_data = {}
if state_file.exists():
    try:
        state_data = json.loads(state_file.read_text())
    except (json.JSONDecodeError, OSError):
        state_data = {"status": "unknown", "error": "Could not read state file"}

# After
state_data = {}
if state_file.exists():
    try:
        state_data = json.loads(state_file.read_text())
    except json.JSONDecodeError as e:
        state_data = {
            "status": "error",
            "error": f"State file corrupt: {e}",
            "phase": "error",
        }
    except PermissionError:
        state_data = {
            "status": "error",
            "error": "State file is unreadable (permission denied). Check ownership of /data/.pipeline-state.json.",
            "phase": "error",
        }
    except OSError as e:
        state_data = {
            "status": "error",
            "error": f"State file read failed: {e}",
            "phase": "error",
        }
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/
git commit -m "$(cat <<'EOF'
fix(search): /status surfaces permission/disk errors structurally

Was: any read failure became 'status: unknown' which the frontend
rendered as empty.

Now: distinct status='error' with a useful error message for each
class (corrupt JSON, permission denied, generic OSError).

Closes: CB17

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: /status log-capture failure → completed_unverified (CB16)

**File:** `services/search/main.py:1691-1700`

**Bug evidence:** `except: pass` on log capture produces empty `last_logs`, which the verdict logic treats as "interrupted" (no evidence of clean exit).

- [ ] **Step 1: Write failing test**

```python
def test_clean_exit_with_failed_log_capture_is_completed_unverified(client, ...):
    """If the container exited cleanly (exit 0) but log capture failed
    (e.g., container already removed), verdict should be 'completed_unverified',
    not 'interrupted'."""
    # Mock container with attrs.State.ExitCode == 0 and logs() raising
    ...
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Track log-capture-failure separately**

```python
# Before
try:
    last_logs = container.logs(tail=100, stdout=True, stderr=True).decode()
except Exception:
    pass  # last_logs stays None, downstream verdict is 'interrupted'

# After
log_capture_failed = False
log_capture_error = None
try:
    last_logs = container.logs(tail=100, stdout=True, stderr=True).decode()
except docker.errors.APIError as e:
    last_logs = None
    log_capture_failed = True
    log_capture_error = str(e)

# Use log_capture_failed downstream:
if exit_code == 0:
    verdict = "completed"
elif log_capture_failed:
    verdict = "completed_unverified"  # new state — exit signal unclear
    state_data["last_logs_error"] = log_capture_error
else:
    verdict = "interrupted"
```

This introduces a new status `completed_unverified`. Update the frontend's `renderGenericProgress` to handle it (see Task 21 — render as completed-with-warning).

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/
git commit -m "$(cat <<'EOF'
fix(search): clean exit with failed log capture isn't 'interrupted'

Was: empty last_logs + exit 0 was indistinguishable from a real crash.

Now: 'completed_unverified' status records the log-capture error
without falsely flagging the run as interrupted. Frontend renders
as 'completed (logs unavailable)' — see T21.

Closes: CB16

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: /cancel surfaces stop() failures (CB18)

**File:** `services/search/main.py:1812-1828`

**Bug evidence:** /cancel returns `{"status": "cancelling"}` even when `container.stop()` raised — user thinks cancel succeeded but the container is still running.

- [ ] **Step 1: Write failing test**

```python
def test_cancel_surfaces_stop_failure(client, ...):
    """If container.stop() raises, /cancel must NOT return success."""
    mock_container = MagicMock()
    mock_container.stop.side_effect = docker.errors.APIError("could not stop")
    ...
    resp = client.post("/admin/pipeline/cancel")
    assert resp.status_code == 503
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Catch and surface**

```python
try:
    container.stop(timeout=30)
except docker.errors.APIError as e:
    log.error("container.stop() failed: %s", e)
    raise HTTPException(
        status_code=503,
        detail={
            "status": "cancel_failed",
            "message": "Could not stop pipeline container.",
            "hint": "The container may still be running. Try again or restart Docker.",
        },
    )
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/
git commit -m "$(cat <<'EOF'
fix(search): /cancel surfaces docker.stop() failures

Was: cancel returned 'cancelling' even when stop() raised — user
thought cancel worked but container was still running.

Now: stop() failures return structured 503 with actionable hint.

Closes: CB18

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Wrap raw Docker exceptions in /start (CB20)

**File:** `services/search/main.py:1619-1622`

**Bug evidence:** Generic `except Exception as e: raise HTTPException(500, f"Failed to start: {e}")` leaks raw Docker exception strings to the user `alert()`.

- [ ] **Step 1: Write failing test**

```python
def test_start_does_not_leak_internal_docker_strings(client, sample_noaa_body):
    """Verify a 5xx response is a structured envelope, not a raw exception
    string. Asserts on the SHAPE of the response (positive structural
    invariant), not on absences (negative pattern matches)."""
    mock_client = MagicMock()
    mock_client.containers.run.side_effect = Exception(
        "HTTP 500 Internal Server Error for unix:///var/run/docker.sock"
    )
    mock_client.containers.get.side_effect = docker.errors.NotFound("none")
    mock_client.images.get.return_value = MagicMock()
    mock_client.networks.list.return_value = []
    with patch("services.search.main._get_docker_client", return_value=mock_client):
        resp = client.post("/admin/pipeline/start", json=sample_noaa_body)

    assert resp.status_code in (500, 503), f"got {resp.status_code}: {resp.text}"
    body = resp.json()
    detail = body.get("detail", {})
    # Positive invariant: detail must be a structured object with a status field
    assert isinstance(detail, dict), f"detail must be a dict, got {type(detail)}: {detail!r}"
    assert detail.get("status") in ("internal_error", "docker_unavailable"), \
        f"detail.status missing or unexpected: {detail}"
    assert detail.get("message"), "detail.message must be a non-empty string"
    # Negative cross-checks (belt + suspenders): no internal-path strings
    assert "unix:///" not in resp.text
    assert "docker.sock" not in resp.text
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Wrap distinct exception classes with sanitized messages**

Replace the generic `except Exception` near the end of the /start handler:

```python
# Before
except Exception as e:
    raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {e}")

# After
except docker.errors.ImageNotFound:
    raise HTTPException(
        status_code=422,
        detail={
            "status": "image_missing",
            "message": "Pipeline image not built.",
            "hint": "Run 'docker compose --profile pipeline build' on the host.",
        },
    )
except docker.errors.APIError as e:
    log.exception("Docker APIError in pipeline_start")
    raise HTTPException(
        status_code=503,
        detail={
            "status": "docker_unavailable",
            "message": "Docker daemon error preventing pipeline launch.",
            "hint": "Try again in a moment, or check 'docker ps'.",
        },
    )
except Exception:
    log.exception("Unexpected error in pipeline_start")
    raise HTTPException(
        status_code=500,
        detail={
            "status": "internal_error",
            "message": "Unexpected error preventing pipeline launch. Check server logs.",
        },
    )
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/
git commit -m "$(cat <<'EOF'
fix(search): structured error responses at /start (no raw Docker strings)

Was: generic except leaked raw Docker exception strings to user alerts,
exposing internal paths/URLs and offering no recovery hint.

Now: ImageNotFound -> 422 with build hint; APIError -> 503 with retry
hint; unexpected -> 500 with 'check logs' message. log.exception() at
each branch so the actual error is captured server-side.

Closes: CB20

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 2 review checkpoint

After Tasks 4-14, run the **mandatory review loop** (3+ rounds, see preamble). Specifically check:
- [ ] Every Docker exception path has a structured error response
- [ ] No bare `except: pass` remains in main.py — `git grep -E 'except\s*:?\s*pass' services/search/main.py` should show only intentional NotFound handlers
- [ ] Full test suite passes: `python -m pytest tests/ services/search/tests/ -v`
- [ ] Live curl smoke test (with auth header):
  ```bash
  AUTH='-H X-Config-Source: <whatever-the-frontend-sends>'
  curl -s -X POST $AUTH http://localhost:80/admin/pipeline/clear?type=imagery
  curl -s $AUTH http://localhost:80/admin/pipeline/status?type=imagery
  ```

---

# Phase 3 — NAIP/Sentinel state-file plumbing (CB7)

### Task 15: `acquire_naip.py` accepts `--state-file` argument

**File:** `scripts/acquire_naip.py:545`

**Bug evidence:** Hardcodes `state_path = output_path.parent / ".pipeline-state.json"`, but the frontend polls `.naip-state.json`.

- [ ] **Step 1: Write failing test**

Add to `tests/test_acquire_naip.py`:

```python
def test_acquire_naip_writes_to_state_file_arg(tmp_path):
    """When --state-file is provided, progress writes go there, not to
    the legacy .pipeline-state.json default."""
    custom_state = tmp_path / ".custom-state.json"
    # Run acquire_naip with mocked downloads, --state-file=custom_state
    # Assert: custom_state was written, .pipeline-state.json was NOT
    ...
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Add CLI arg + use it**

In `scripts/acquire_naip.py`, find the argparse setup and add:

```python
parser.add_argument(
    "--state-file",
    type=Path,
    default=None,
    help="Path to write progress state. Default: <output_dir>/.pipeline-state.json (legacy)",
)
```

At L545:

```python
# Before
state_path = output_path.parent / ".pipeline-state.json"

# After
state_path = args.state_file or (output_path.parent / ".pipeline-state.json")
```

- [ ] **Step 4: Run test, expect pass**

- [ ] **Step 5: Commit**

```bash
git add scripts/acquire_naip.py tests/test_acquire_naip.py
git commit -m "$(cat <<'EOF'
fix(pipeline): acquire_naip.py accepts --state-file

Was: hardcoded .pipeline-state.json regardless of pipeline type.
Frontend polls .naip-state.json — never saw NAIP progress.

Now: --state-file argument routes progress to the correct file.
Default preserved for back-compat with direct CLI use.

Closes: CB7 (script side)

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: `acquire_sentinel.py` accepts `--state-file` argument

**File:** `scripts/acquire_sentinel.py:102`

Same pattern as Task 15. Test in `tests/test_acquire_sentinel.py`.

- [ ] Steps as before; commit closes "CB7 (sentinel side)".

---

### Task 17: /start passes correct `--state-file` to NAIP and Sentinel containers

**File:** `services/search/main.py:1465-1480` (Sentinel + NAIP command builders)

- [ ] **Step 1: Write failing test**

```python
def test_start_naip_passes_state_file_arg(client, mock_docker_for_start, ...):
    """/start NAIP must include --state-file=/data/.naip-state.json."""
    body = {"type": "naip", "bbox": "-114,32,-112,34"}
    with patch("services.search.main._get_docker_client", return_value=mock_docker_for_start):
        client.post("/admin/pipeline/start", json=body)
    # Inspect the command that was passed to containers.run()
    call_args = mock_docker_for_start.containers.run.call_args
    command = call_args.kwargs.get("command") or call_args.args[1]
    assert "--state-file" in command
    idx = command.index("--state-file")
    assert command[idx + 1] == "/data/.naip-state.json"
```

- [ ] **Step 2: Run, expect failure**

- [ ] **Step 3: Update command builders**

```python
# In NAIP command builder around L1472
elif is_naip:
    command = [
        "python3", "/scripts/acquire_naip.py",
        f"--bbox={body.bbox}",
        "--output", f"/data/{mbtiles_path.name}",
        "--staging", "/data/naip_staging",
        "--counties-db", "/data/counties.sqlite",
        "--state-file", "/data/.naip-state.json",  # NEW
    ]
    if body.counties:
        command.append(f"--counties={body.counties}")

# Similarly for sentinel:
elif is_sentinel:
    command = [
        "python3", "/scripts/acquire_sentinel.py",
        f"--bbox={body.bbox}",
        "--output", f"/data/{mbtiles_path.name}",
        "--staging", "/data/sentinel_staging",
        "--state-file", "/data/.sentinel-state.json",  # NEW
    ]
```

- [ ] **Step 4: Run, expect pass**

- [ ] **Step 5: Commit**

```bash
git add services/search/main.py services/search/tests/
git commit -m "$(cat <<'EOF'
fix(search): /start passes correct --state-file to NAIP/Sentinel

Closes the CB7 chain: NAIP and Sentinel pipelines now write progress
to the file the frontend actually polls. Previously, NAIP runs wrote
to .pipeline-state.json (stomping imagery state) while the NAIP card
read .naip-state.json (always empty).

Closes: CB7

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 3 review checkpoint

3+ review rounds. Specifically: trigger a NAIP pipeline (mocked Docker is fine for the check) and verify the frontend NAIP card receives non-empty progress JSON from `/admin/pipeline/status?type=naip`.

---

# Phase 4 — Frontend (CB5, CB6, CB22, CB3-frontend, CB21)

**Reminder:** Frontend code uses textContent + appendChild, never innerHTML with computed content. The pre-commit security hook will reject violations.

### Task 18: Bbox-input invalidates per-card stale state (CB5 + CB6)

**File:** `frontend/config/index.html` (cfg-bbox listener at L3003-3005)

**Bug evidence:** `estBoxCustom._diskBlocked` and ack-checkbox state survive bbox redraws → block valid Start clicks with confusing alerts.

- [ ] **Step 1: Identify all per-card stale state**

```bash
grep -nE 'estBox(Custom|Whole)\._[a-zA-Z]+' frontend/config/index.html
```

- [ ] **Step 2: Wire bbox-input to invalidation**

In the cfg-bbox input listener (around L3003), extend it:

```javascript
document.getElementById('cfg-bbox').addEventListener('input', function() {
    syncBboxToMap();
    // Invalidate per-card estimate state when bbox changes — prevents
    // stale _diskBlocked flags or ack checkboxes from blocking Start.
    document.querySelectorAll('[id$="-est-custom"], [id$="-est-whole"]').forEach(function(el) {
        el._diskBlocked = false;
        el.style.display = 'none';
        // Use replaceChildren() — DOM-safe, preferred over innerHTML='' for
        // consistency with the codebase's no-innerHTML convention.
        if (el.replaceChildren) el.replaceChildren();
        else { while (el.firstChild) el.removeChild(el.firstChild); }
    });
});
```

- [ ] **Step 3: Manual test**

Open `frontend/config/index.html` in a browser:
1. Expand NOAA NAIP card
2. Estimate a large bbox — note the disk-blocked warning if any
3. Re-draw a small bbox in the map
4. Click Start (Custom area)
5. Should NOT see the "peak working set exceeds free disk" alert

- [ ] **Step 4: Commit**

```bash
git add frontend/config/index.html
git commit -m "$(cat <<'EOF'
fix(frontend): bbox-input invalidates stale per-card estimate state

Was: estBoxCustom._diskBlocked and prior ack-checkbox state survived
bbox redraws — Start click alerted with stale information.

Now: bbox-input listener clears all per-card estimate state, hiding
the estimate box and resetting flags. User must re-Estimate with
the fresh bbox before Start re-enables.

DOM safety: uses replaceChildren()/removeChild loop, not innerHTML.

Closes: CB5, CB6

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: NOAA card remembers last-active tab (CB22)

**File:** `frontend/config/index.html:1416-1420`

**Bug evidence:** `<button class="noaa-tab active" data-tab="whole">` is hardcoded. User retrying a Custom-area failure must manually re-select the tab.

- [ ] **Step 1: Remove the hardcoded `active` from the rendered HTML; set it via classList post-render**

The card body currently inserts a static template string with `class="noaa-tab active"` baked in. To avoid the security hook flagging any innerHTML manipulation we touch, leave the template string with NO `active` class on either tab, and apply the active class after insertion:

```javascript
// In the tab strip template (around L1416), remove `active` from the whole-state tab:
//   Before: '<button class="noaa-tab active" data-tab="whole" role="tab">Whole state</button>'
//   After:  '<button class="noaa-tab" data-tab="whole" role="tab">Whole state</button>'
//
// (The Custom-area tab is already in non-active state in the template; leave it.)

// After the body.innerHTML = '...' call, add:
var lastTab = sessionStorage.getItem('noaa-last-tab') || 'whole';
body.querySelectorAll('.noaa-tab').forEach(function(tabBtn) {
    if (tabBtn.getAttribute('data-tab') === lastTab) {
        tabBtn.classList.add('active');
    } else {
        tabBtn.classList.remove('active');
    }
});

// Find the existing tab-click handler (search for "data-tab"). Add a sessionStorage write:
//   tab.addEventListener('click', function() {
//       var clickedTab = tab.getAttribute('data-tab');
//       sessionStorage.setItem('noaa-last-tab', clickedTab);  // NEW LINE
//       // ... existing tab-switch logic
//   });
```

This avoids any new innerHTML usage and keeps the active-class state outside the template string, where the security hook can't object to the empty-string interpolation.

- [ ] **Step 2: Manual test**

1. Open NOAA card, switch to Custom-area tab
2. Collapse the card
3. Re-expand — should still be on Custom-area tab

- [ ] **Step 3: Commit**

```bash
git add frontend/config/index.html
git commit -m "$(cat <<'EOF'
fix(frontend): NOAA card remembers last-active tab

Was: NOAA card always opened on Whole-state tab. User retrying a
Custom-area failure had to manually re-select.

Now: tab choice persists via sessionStorage, scoped to the tab.

Closes: CB22

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 20: Dismiss button next to error message (CB3 frontend side)

**File:** `frontend/config/index.html:2739-2743`

**Bug evidence:** Error rendering has no dismiss control. Combined with CB3 server side (Task 8), users need a button to call /clear.

- [ ] **Step 1: Modify the error branch in renderGenericProgress**

In the `else if (d.status === 'error')` branch (around L2739), change content construction to use safe DOM methods:

```javascript
} else if (d.status === 'error') {
    progressDiv.style.display = 'none';
    completedEl.style.display = '';
    completedEl.className = 'status status-error';

    // Clear existing content via safe DOM API.
    if (completedEl.replaceChildren) {
        completedEl.replaceChildren();
    } else {
        while (completedEl.firstChild) completedEl.removeChild(completedEl.firstChild);
    }

    // Build label as text nodes (no innerHTML).
    var errText = (sourceLabel || 'Download') + ' failed' + (ago ? ' ' + ago : '');
    completedEl.appendChild(document.createTextNode(errText));
    if (d.error) {
        completedEl.appendChild(document.createTextNode(' — '));
        completedEl.appendChild(document.createTextNode(d.error));
    }

    // Append Dismiss button.
    var dismissBtn = document.createElement('button');
    dismissBtn.type = 'button';
    dismissBtn.className = 'btn-secondary';
    dismissBtn.style.marginLeft = '8px';
    dismissBtn.textContent = 'Dismiss';
    dismissBtn.addEventListener('click', function() {
        var pipelineType = d.type || 'imagery';
        dismissBtn.disabled = true;
        var origText = dismissBtn.textContent;
        dismissBtn.textContent = 'Clearing…';
        cfgFetch('/admin/pipeline/clear?type=' + encodeURIComponent(pipelineType), { method: 'POST' })
            .then(function(r) {
                if (!r.ok) {
                    return r.json().then(function(err) {
                        var msg = (err.detail && err.detail.message) || err.detail || 'unknown error';
                        alert('Dismiss failed: ' + msg);
                        dismissBtn.disabled = false;
                        dismissBtn.textContent = origText;
                    });
                }
                fetchAll();
            })
            .catch(function(e) {
                alert('Dismiss failed: ' + (e.message || 'network error'));
                dismissBtn.disabled = false;
                dismissBtn.textContent = origText;
            });
    });
    completedEl.appendChild(dismissBtn);
}
```

- [ ] **Step 2: Manual test**

1. Force an error state (start a multi-state bbox after CB1+CB2 fix should now do this cleanly)
2. Confirm Dismiss button appears
3. Click Dismiss — error should clear, card returns to startable state

- [ ] **Step 3: Commit**

```bash
git add frontend/config/index.html
git commit -m "$(cat <<'EOF'
fix(frontend): Dismiss button next to error message

Calls POST /admin/pipeline/clear (T8) when clicked. Disables itself
while in flight. Surfaces server errors via alert().

DOM-safe: textContent + appendChild only, no innerHTML with
computed content.

Closes: CB3 (frontend side)

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 21: Multi-state error UX + server message + completed_unverified rendering (CB21 + T12 follow-up)

**Files:**
- `frontend/config/index.html` (startPipeline error handler around L1338; renderGenericProgress new completed_unverified branch)
- `scripts/acquire_imagery.py:2237-2240` (multi-state guardrail message)

- [ ] **Step 1: Frontend — handle 409 multi_state_unsupported with rich message**

In the `startPipeline` helper (~L1328), enhance the error branch:

```javascript
function startPipeline(src, params) {
    var bbox = document.getElementById('cfg-bbox').value;
    var body = { type: src.pipelineType, bbox: bbox };
    if (src.pipelineMode) body.mode = src.pipelineMode;
    Object.keys(params).forEach(function(k) { body[k] = params[k]; });
    cfgFetch('/admin/pipeline/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    }).then(function(resp) {
        if (!resp.ok) {
            return resp.json().then(function(d) {
                // Structured multi-state error from /start (CB2)
                if (resp.status === 409 && d.detail && d.detail.status === 'multi_state_unsupported') {
                    var states = (d.detail.states || []).map(function(s) { return s.toUpperCase(); });
                    alert(
                        'This bbox covers ' + states.length + ' states: ' + states.join(', ') + '.\n\n' +
                        'Multi-state dispatch is not yet implemented. Either:\n' +
                        '• Narrow the bbox to fit one state, or\n' +
                        '• Use the "Whole state" tab to dispatch one state at a time.'
                    );
                    return;
                }
                // Other structured errors with a message field
                if (d.detail && d.detail.message) {
                    alert(d.detail.message + (d.detail.hint ? '\n\nHint: ' + d.detail.hint : ''));
                    return;
                }
                alert(d.detail || 'Start failed');
            });
        }
        toggleCardExpand(null);
        fetchAll();
    }).catch(function(e) { alert('Start failed: ' + e.message); });
}
```

- [ ] **Step 2: Frontend — handle completed_unverified status in renderGenericProgress**

In `renderGenericProgress`, add a new branch:

```javascript
} else if (d.status === 'completed_unverified') {
    progressDiv.style.display = 'none';
    completedEl.style.display = '';
    completedEl.className = 'status status-warn';
    if (completedEl.replaceChildren) completedEl.replaceChildren();
    else while (completedEl.firstChild) completedEl.removeChild(completedEl.firstChild);
    var info = d.items_done ? ' — ' + d.items_done.toLocaleString() + ' ' + (d.item_unit || 'items') : '';
    completedEl.appendChild(document.createTextNode(
        (sourceLabel ? sourceLabel + ' c' : 'C') + 'ompleted (logs unavailable)' + (ago ? ' ' + ago : '') + info
    ));
}
```

- [ ] **Step 3: Pipeline-side message — improve `acquire_imagery.py:2237-2240`**

After CB1 is in (polygon intersection), the multi-state guardrail only fires for genuine cross-border bboxes. Make the message say this clearly:

```python
# Before
multi_states = ", ".join(e["usps"] for e in candidates)
msg = (
    f"bbox intersects {len(candidates)} states ({multi_states}); "
    "multi-state dispatch is not yet implemented. Pick a single "
    "state from the 'Whole state' tab, or narrow the bbox."
)

# After
multi_states = ", ".join(e["usps"] for e in candidates)
msg = (
    f"bbox crosses the border between {len(candidates)} states "
    f"({multi_states}). Multi-state dispatch is not yet implemented. "
    "Either narrow the bbox to fit fully within one state, or use "
    "the 'Whole state' tab to dispatch each state separately. "
    "(If you reached this from the admin panel, the server-side "
    "guard at /admin/pipeline/start should have caught this earlier — "
    "this fallback exists for direct CLI invocations.)"
)
```

- [ ] **Step 4: Manual test**

After all fixes from T7 + T20 + T21:
1. Submit a genuine cross-border bbox (Bullhead City AZ/NV) → 409 with rich alert listing both states + suggestion
2. Force an error → Dismiss button appears, click it → state clears
3. Submit a valid Lake Mead bbox → succeeds (no false-positive 409)

- [ ] **Step 5: Commit**

```bash
git add frontend/config/index.html scripts/acquire_imagery.py
git commit -m "$(cat <<'EOF'
fix(frontend,pipeline): multi-state error UX + completed_unverified rendering

Frontend:
- startPipeline 409 handler renders rich message when /start returns
  structured multi_state_unsupported (T7). Lists both states +
  actionable next-steps.
- New renderGenericProgress branch for completed_unverified (T12) —
  surfaces clean exits with missing logs as warn-state, not error.

Pipeline:
- acquire_imagery.py multi-state guardrail message clarifies that the
  server should have caught this; fallback exists for CLI use.

DOM-safe: textContent + appendChild throughout.

Closes: CB21 (and follow-up rendering for T12)

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Phase 4 review checkpoint

3+ review rounds. Specifically:
- [ ] Manual end-to-end test: submit multi-state bbox → see 409 with rich message → re-draw single-state bbox → submit → succeeds. No alerts about diskBlocked or ack checkbox if the bbox is fresh.
- [ ] Dismiss button clears error and the card returns to a clean Start-able state.
- [ ] Tab persistence works (T19): switch to Custom, collapse, expand → still on Custom.

---

# Phase 5 — Final integration & docs

### Task 22: End-to-end regression test for the user's reported flow

**File:** `services/search/tests/test_pipeline_sticky_error_regression.py` (NEW)

Write a test that simulates: error state present → user submits valid single-state bbox → pipeline starts cleanly. This is the primary regression test for the entire bug-cluster.

```python
"""Regression test for the 2026-04-24 bug-hunt: NOAA pipeline sticky error.

Reproduces the user's reported flow:
1. Submit a multi-state bbox - server rejects with 409 (post-CB2)
2. Server NEVER spawns a doomed container (post-CB2)
3. State file NOT clobbered with stale error (post-CB2/CB4)
4. User redraws single-state bbox - server accepts (post-CB1)
5. If pre-existing error state exists, /clear dismisses it (post-CB3)
"""
import json
from unittest.mock import MagicMock, patch
import docker.errors


def test_user_can_recover_from_error_state(client, tmp_data_dir, sample_noaa_body):
    state_file = tmp_data_dir / ".pipeline-state.json"

    # Arrange: error state present (mimics user's reported scenario)
    state_file.write_text(json.dumps({
        "status": "error", "type": "imagery", "mode": "noaa",
        "error": "stuck error from prior multi-state attempt",
        "phase": "error",
    }))

    # Act 1: Dismiss
    mock_client = MagicMock()
    mock_client.containers.list.return_value = []  # no real container
    with patch("services.search.main._get_docker_client", return_value=mock_client):
        resp = client.post("/admin/pipeline/clear?type=imagery")
    assert resp.status_code == 200, resp.text
    assert json.loads(state_file.read_text()) == {}

    # Act 2: Submit valid single-state bbox (Lake Mead, NV-only after CB1)
    body = dict(sample_noaa_body)
    body["bbox"] = "-115.6982,35.8829,-114.7706,36.5005"
    body["state"] = None  # force bbox-mode dispatch
    mock_run_client = MagicMock()
    mock_run_client.containers.list.return_value = []
    mock_run_client.containers.get.side_effect = docker.errors.NotFound("none")
    mock_run_client.images.get.return_value = MagicMock()
    mock_run_client.containers.run.return_value = MagicMock(id="abc123")
    mock_run_client.networks.list.return_value = []
    with patch("services.search.main._get_docker_client", return_value=mock_run_client):
        resp = client.post("/admin/pipeline/start", json=body)

    # Must NOT be 409 multi_state_unsupported (CB1 fix means CA isn't matched)
    if resp.status_code == 409:
        assert resp.json().get("detail", {}).get("status") != "multi_state_unsupported"

    # State file should now show running, not error
    state = json.loads(state_file.read_text())
    assert state.get("status") in ("running", None) and state.get("status") != "error"


def test_genuine_multi_state_bbox_returns_409_without_dispatch(client, tmp_data_dir):
    """The bbox in this test genuinely straddles AZ/NV (Colorado River).
    Must reject with 409 BEFORE dispatching a container."""
    body = {
        "type": "imagery", "mode": "noaa",
        "bbox": "-114.62,35.13,-114.55,35.20",
        "acknowledge_missing": True,
    }
    mock_client = MagicMock()
    with patch("services.search.main._get_docker_client", return_value=mock_client):
        resp = client.post("/admin/pipeline/start", json=body)
    assert resp.status_code == 409
    assert resp.json()["detail"]["status"] == "multi_state_unsupported"
    # Critically: containers.run must NOT have been called
    assert not mock_client.containers.run.called, "container was spawned despite 409"
```

- [ ] Steps as before; commit message references "Closes regression test for CB1+CB2+CB3 chain."

---

### Task 23: Update `docs/pitfalls/testing-pitfalls.md`

Append the 4 new pitfalls identified in the consolidation report's Phase 4 (Test Gap Analysis):

1. Test negative paths of every server gate
2. Test error recoverability, not just error production
3. Test invariants that span component boundaries
4. Mock failure modes of external clients

- [ ] **Step 1: Read the file first**

```bash
cat docs/pitfalls/testing-pitfalls.md | head -50
```

Match its existing format exactly. Each pitfall entry should be actionable, not narrative.

- [ ] **Step 2: Append new entries**

Use the file's existing numbering scheme. Example for the first:

```markdown
## TP-NN. Test negative paths of every server gate

For any HTTP endpoint with conditional rejections (auth, validation, state
checks), add a test for *each* rejection case. Don't just test the happy path.

**Why:** A bug hunt on 2026-04-24 found that /admin/pipeline/start had no
multi-state guard despite already computing the data needed to enforce one.
The happy-path test passed; no test exercised the rejection. Result: every
multi-state bbox dispatched a container that crashed within seconds.

**How to apply:** For each `raise HTTPException(...)` in a handler, write a
test that asserts the request that triggers it returns the expected status code
and body shape. The test name should mention the rejection reason explicitly.
```

(Apply the same template for the other three pitfalls.)

- [ ] **Step 3: Commit**

```bash
git add docs/pitfalls/testing-pitfalls.md
git commit -m "$(cat <<'EOF'
docs(pitfalls): add 4 testing pitfalls from 2026-04-24 bug hunt

- Test negative paths of every server gate
- Test error recoverability, not just error production
- Test invariants that span component boundaries
- Mock failure modes of external clients

Each surfaced as a missed-test class during the bug-hunt-cycle for
the NOAA pipeline sticky-error symptom.

Refs: dev/bug-hunts/2026-04-24-pipeline-sticky-error-consolidated.md

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 24: Update `dev/implementation-log.md`

Add an entry at the top:

```markdown
## 2026-04-24 - NOAA pipeline sticky-error remediation (17 bugs fixed)

Bug-hunt-cycle (3 hunters) on the user-reported "multi-state error is sticky"
symptom surfaced 22 confirmed bugs, design decisions D1-D5 by Cameron, and
this 24-task fix plan. Tasks 1-23 closed CB1-9, CB11, CB15-18, CB20-22, plus
CB7 (orthogonal NAIP/Sentinel state-file mismatch). Deferred: CB10 (created-state
race), CB13 (state-file fallthrough), CB14 (overloaded sentinel), CB19
(snapshot resolve race) - see appendix in plan file.

Follow-up scheduled: D2(c) - implement multi-state dispatch as separate
brainstorm -> spec -> plan cycle.

Refs:
- dev/bug-hunts/2026-04-24-pipeline-sticky-error-{exploratory,holistic,multipass,consolidated}.md
- dev/plans/2026-04-24-pipeline-sticky-error-remediation-plan.md
```

- [ ] Commit:

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs(impl-log): pipeline sticky-error remediation entry

Agent: <your-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 25: Open PR

Per [CONTRIBUTING.md](../../CONTRIBUTING.md). Title: `fix(pipeline): NOAA sticky-error remediation (17 bugs)`. Body: link to the consolidated bug hunt + this plan, paste the 17-bug summary table.

```bash
gh pr create --title "fix(pipeline): NOAA sticky-error remediation (17 bugs)" --body "$(cat <<'EOF'
## Summary

Closes 17 bugs surfaced by the 2026-04-24 bug-hunt-cycle on the user-reported
"multi-state error is sticky" symptom. Bug hunt found that the symptom is
actually a chain of 4 independent bugs (CB1+CB2+CB3+CB4) compounded by
several frontend stale-state issues; in the process surfaced an orthogonal
architectural bug (NAIP/Sentinel state-file mismatch, CB7) which is also
closed here.

Closes: CB1, CB2, CB3, CB4, CB5, CB6, CB7, CB8, CB9, CB11, CB15, CB16, CB17,
CB18, CB20, CB21, CB22

Deferred to follow-up plans: CB10, CB13, CB14, CB19 (see plan appendix).
Multi-state dispatch implementation (D2(c)) deferred to a separate
brainstorm -> spec -> plan cycle.

## Test plan

- [ ] All existing tests pass: `python -m pytest tests/ services/search/tests/ -v`
- [ ] New regression test passes: `python -m pytest services/search/tests/test_pipeline_sticky_error_regression.py -v`
- [ ] Live test: submit Lake Mead bbox -> succeeds (no false-positive multi-state)
- [ ] Live test: submit Bullhead City bbox -> 409 with rich message, no container spawned
- [ ] Live test: force an error -> Dismiss button works
- [ ] Live test: NAIP pipeline UI shows progress (CB7 fix verified)

Refs:
- dev/bug-hunts/2026-04-24-pipeline-sticky-error-consolidated.md
- dev/plans/2026-04-24-pipeline-sticky-error-remediation-plan.md

Agent: <your-moniker>
EOF
)"
```

---

# Appendix: Bugs identified but not fixed in this cycle

### CB10 — Container in "created" state treated as not running

**Location:** [`services/search/main.py:1175-1187`](../../services/search/main.py#L1175-L1187)
**Evidence:** `_is_pipeline_container_running` matches only `c.status == "running"`. During the brief Docker-bootstrap window (status `created` → `running`), /status reconciler concludes a fresh start has crashed.
**Why deferred:** Lower frequency (sub-second window); D5 chose to focus on CB4 + CB9. The CB9 fix changes the function signature, so layering CB10 on top is a one-line additional change but should be tested independently.
**Recommended fix:** In Task 5's reimplementation, expand the running check to `c.status in ("running", "created", "restarting")`. Ship in a follow-up plan.

### CB13 — `_state_file_for_type` silent fallthrough

**Location:** [`services/search/main.py:1138-1150`](../../services/search/main.py#L1138-L1150)
**Evidence:** Returns the imagery state file for any unknown type. Future callers passing a typo will silently stomp imagery state.
**Recommended fix:** Raise `ValueError` for unknown types; callers must pre-validate.

### CB14 — `_noaa_peak_and_snapshot` overloaded sentinel

**Location:** [`services/search/main.py:1219-1247`](../../services/search/main.py#L1219-L1247)
**Evidence:** Returns `([], 0.0, None)` for 4 distinct conditions; caller emits one error message for all four.
**Recommended fix:** Either return a typed result (`Result[Success, Reason]`) or raise distinct exceptions.

### CB19 — Catalog snapshot resolve race

**Location:** [`services/search/main.py:1336-1340`](../../services/search/main.py#L1336-L1340)
**Evidence:** Pre-lock `_noaa_peak_and_snapshot` resolves a snapshot path; if /refresh runs between that resolve and the pipeline container's pin, the two see different snapshots.
**Recommended fix:** Pass the resolved path through to the container as `--catalog-snapshot=/data/noaa_catalog_snapshots/<TS>.json` rather than re-resolving the symlink in-container.

---

# D2(c) — Multi-state dispatch implementation (out of scope for this plan)

After Phase 5 ships, schedule a separate brainstorm → spec → plan → implementation cycle for actual multi-state bbox dispatch. Infrastructure already exists:
- `build_unified_queue()` at `scripts/acquire_imagery.py:268`
- Per-state result writer at `acquire_imagery.py:367`
- Resolver returning multi-state candidates at `acquire_imagery.py:2208`
- Frontend `partial_failed` retry UI at `frontend/config/index.html:2744+`

Missing: outer loop in `run_noaa()` that iterates candidates when `len(candidates) > 1`, calls each state's `build_unified_queue()`, accumulates `per_state` dict, and writes the final multi-state status.

Estimate: 1 brainstorm, 1 spec round, 1 adversarial review round, 5-8 implementation tasks. Per project rigor, NOT smuggled into a bug-fix plan.

---

# Self-review (executed by author of this plan)

1. **Spec coverage:** All 17 in-scope bugs (CB1-9, 11, 15-18, 20-22) mapped to tasks T1-T22. Out-of-scope kept in appendix. ✓
2. **Placeholder scan:** Test sketches contain `...` (intentional — fresh subagents extend test patterns based on existing fixtures). All non-test code blocks complete. ✓
3. **Type consistency:** `states_intersecting_polygon`, `_load_state_polygons`, `_USPS_TO_SLUG` consistent across T2-T3. `_is_pipeline_container_running` 3-state return consistent T5-onwards. State-file atomic-write pattern (`atomic_write_json`) consistent T6, T8, T9. ✓
4. **Cross-task ordering:** Phase 1 must run before T7 (T7's guard depends on T3's polygon migration). Phase 2 tasks SERIAL within main.py. Phase 3 depends on Phase 2 (T17 modifies the same /start handler T7 just edited). Phase 4 depends on Phase 2 (T20 calls /clear from T8). Documented above. ✓
5. **DOM safety:** All frontend code uses textContent + appendChild + replaceChildren — no innerHTML with computed content. Pre-commit hook will enforce. ✓

# Plan ready for execution
