# Admin Panel Redesign Bug Hunt — Consolidated Findings

**Date:** 2026-04-09
**Scope:** Admin panel redesign — 5 tasks, 11 files changed, 1899 lines added across GPS /status endpoint, enriched /admin/status, osm_poi pipeline support, NGINX tile proxy, and full frontend rewrite.
**Hunters:** Exploratory, Holistic, Multipass

---

## Confirmed Bugs

### B1. `pipeline_status` crashes with 500 for osm_poi pipelines (AttributeError escapes handler)
**Consensus:** Exploratory (only hunter to find this — verified by consolidation)
**Location:** `services/search/main.py:1175-1181`
**Evidence:** When an osm_poi pipeline starts, the state file is written with `"bbox": null` and `"zoom": null` (lines 1097-1098). In `pipeline_status`, line 1175 checks `if "bbox" in state_data and "zoom" in state_data` — both keys exist (value is null), so the condition is True. It calls `_parse_bbox(None)`, and `None.split(",")` raises `AttributeError`. The except clause at line 1180 only catches `(ValueError, TypeError)`, not `AttributeError`.
**Impact:** Any GET to `/admin/pipeline/status?type=osm_poi` returns 500 error whenever an osm_poi pipeline has been started or completed. Frontend polls this every 10 seconds, so the OSM POI progress section is permanently broken once an extraction is triggered.
**Blast radius:** Fix is localized to `pipeline_status` in `services/search/main.py`. No other callers affected.
**Fix approach:** Change condition from `if "bbox" in state_data and "zoom" in state_data` to `if state_data.get("bbox") and state_data.get("zoom")`. This checks for both key presence and truthiness (non-null).

### B2. Docker client used after close in `pipeline_status` — crash logs never captured
**Consensus:** All three hunters found this (strong signal)
**Location:** `services/search/main.py:1140, 1156-1162`
**Evidence:** `client.close()` at line 1140 in a `finally` block. At line 1156, `if client:` evaluates True (closed object is still truthy), then `client.containers.get()` on the closed client fails. The `except Exception: pass` silently swallows the error.
**Impact:** When a pipeline container crashes, the reconciliation correctly marks state as "interrupted" with completion timestamps, but `last_logs` is never populated. Crash diagnosis information is silently lost — significant on an offline system where logs may not be persisted elsewhere.
**Blast radius:** Fix is localized to `pipeline_status` in `services/search/main.py`. Restructure the try/finally to keep the client alive until after reconciliation.
**Fix approach:** Move `client.close()` out of the inner `try/finally` into a broader scope that wraps the entire reconciliation block.

### B3. Pipeline banner shows no progress for elevation/OSM pipelines
**Consensus:** Holistic found this; Multipass noted the single-type design
**Location:** `frontend/config/index.html:448-475`
**Evidence:** `renderPipelineBanner()` is only called from the imagery pipeline callback (line 990). For elevation and OSM, the banner shows a title string via `_elevRunning`/`_osmRunning` flags but the progress bar stays at 0% and detail text is empty. The progress data is available from the respective pipeline status responses but isn't passed to the banner function.
**Impact:** When an elevation or OSM pipeline is running, the dashboard banner indicates something is running but shows no progress. The Pipelines tab shows correct progress — this only affects the dashboard summary banner.
**Blast radius:** Frontend-only fix. Modify `renderPipelineBanner` to accept data from any pipeline type, and call it from all three pipeline callbacks.
**Fix approach:** Pass pipeline data from elevation and OSM callbacks to `renderPipelineBanner`, with adapted progress calculation for each type.

---

## Design Decisions Requiring User Input

### D1. `admin_status` blocks the async event loop with synchronous calls
**Location:** `services/search/main.py:656-810`
**The concern:** All three hunters flagged this. The endpoint calls synchronous Docker API (`client.containers.list`, `c.attrs`, `c.logs`), `subprocess.run` (openssl x509 twice), synchronous SQLite COUNT queries, and `shutil.disk_usage` — all without `asyncio.to_thread()`. This blocks the event loop for 1-5 seconds every 10-second poll cycle.
**Why this needs a decision:** The fix (wrapping in `to_thread()`) is straightforward but touches 4 helper functions and the main admin_status body. It's medium-complexity refactoring vs. living with periodic search service stalls.
**Options:**
  - **A) Wrap sync calls in `asyncio.to_thread()`** — Pros: Unblocks event loop, search queries no longer stall during admin polls. Cons: Medium refactoring effort, slightly more complex code.
  - **B) Accept the blocking** — Pros: No code change. Cons: 1-5s search service stalls every 10s when config panel is open. Only affects users who have the config panel open while searching.
  - **C) Use async Docker client (aiodocker)** — Pros: Most correct solution. Cons: New dependency, larger refactor, more risk.
**Recommendation:** Option A. The config panel and search queries share the same service, so blocking is a real issue whenever the admin panel is open. `to_thread()` is low-risk and well-understood.

### D2. Hardcoded paths in `pipeline_cancel` diverge from DATA_DIR
**Location:** `services/search/main.py:1193-1197`
**The concern:** `pipeline_cancel` uses `Path("/data/.pipeline-state.json")` etc., while `_state_file_for_type()` constructs paths from `DATA_DIR`. In production they're identical, but tests can't override with `tmp_path`.
**Why this needs a decision:** This is a testability/consistency issue. The current code works in production but would break if DATA_DIR ever changed and makes the cancel function harder to unit test.
**Options:**
  - **A) Refactor to use `_state_file_for_type()`** — iterate over known types. Clean, DRY.
  - **B) Leave as-is** — works in production, cancel isn't currently unit tested.
**Recommendation:** Option A. Small change, improves consistency and testability.

---

## False Positives

### FP1. Valhalla port 8094 overlap with config panel
**Flagged by:** Multipass (#8)
**Why invalid:** Valhalla binds 8094 on the host. The config panel listens on 8094 *inside* the frontend container, mapped to host 8097. These are different network namespaces — no conflict. The multipass hunter correctly demoted this on analysis.

### FP2. GPS `_position` dict non-atomic replacement
**Flagged by:** Multipass (#5)
**Why invalid:** CPython's GIL guarantees dict reference assignment is atomic. The pattern `_position = {...}` is a single reference swap. While theoretically fragile under non-GIL Python, this is a CPython-only project running on a Pi 5. Not a practical bug.

### FP3. CSRF / `X-Config-Source` on read-only public admin endpoints
**Flagged by:** Holistic (design concern)
**Why invalid:** Read-only endpoints like `/admin/status` and `/admin/pipeline/status` are intentionally accessible on the public port without `X-Config-Source`. They return operational data (service health, disk usage) — no secrets. `/admin/credentials/status` only returns `{"m2m_configured": true/false}` — knowing whether credentials exist is not a security-sensitive fact in a mesh network deployment.

### FP4. No bbox/latitude validation in `estimate_tile_count`
**Flagged by:** Exploratory (design concern)
**Why invalid:** The function is only called from `pipeline_status` (after `_parse_bbox` succeeds) and from the frontend's `estimateTiles()` (user-drawn bboxes). In both cases, extreme latitudes (near ±90°) would cause math errors, but the minimap's viewport limits prevent drawing such bboxes, and the backend's `_parse_bbox` doesn't validate latitude ranges either. This is a pre-existing pattern across the codebase, not introduced by the admin panel redesign.

---

## Bugs Outside Primary Scope

### O1. Broad `except Exception: pass` throughout pipeline orchestration
**Location:** Multiple locations in `services/search/main.py` (lines 1137-1138, 1161-1162, 1168-1169, 1206-1207)
**The concern:** Pre-existing pattern where all exceptions are silently swallowed. Makes debugging pipeline issues significantly harder.
**Blast radius:** Many call sites. Adding logging would be a cross-cutting change.
**Recommendation:** Document for later. Add `logger.exception()` calls in a future cleanup pass.

### O2. `_parse_zoom` gives confusing errors for edge-case inputs
**Location:** `services/search/main.py:113-121`
**The concern:** `"-1-14"` produces 3 parts from `split("-")`, giving "must be in format 'min-max'" instead of "negative values not allowed". The frontend always sends well-formed input from select options, so this is unreachable via the UI.
**Blast radius:** Only affects direct API callers with malformed input. Error message is confusing but non-dangerous.
**Recommendation:** Document for later. Low priority.

### O3. Tile size shown as "GB" but computed in GiB
**Location:** `frontend/config/index.html:333`, `services/search/main.py:937`
**The concern:** `count * 20 * 1024 / (1024**3)` computes GiB but labels it "GB". ~7% underestimate on large downloads.
**Blast radius:** Frontend display text only. No functional impact.
**Recommendation:** Document for later. Cosmetic.

### O4. `pipeline_cancel` JSON formatting inconsistency
**Location:** `services/search/main.py:1204`
**The concern:** `pipeline_start` writes state with `indent=2`, `pipeline_cancel` writes without indent.
**Blast radius:** Cosmetic. No functional impact.
**Recommendation:** Fix alongside D2 if that refactor is accepted.

---

## Test Gap Analysis

### B1. `pipeline_status` crashes for osm_poi (AttributeError)
**Why missed:** The test `test_completed_at_on_state` tests reconciliation for imagery (bbox is non-null). No test exists for `pipeline_status` with osm_poi type where bbox/zoom are null. The test suite tests osm_poi *start* but not osm_poi *status polling*.
**Pitfall coverage:** Not covered by existing pitfalls. This is a new gap: "test each pipeline type's full lifecycle, not just start."
**Catch test:** `test_osm_poi_status_after_start` — create state file with `{"status": "running", "type": "osm_poi", "bbox": null, "zoom": null}`, call `GET /admin/pipeline/status?type=osm_poi`, assert 200 (not 500).

### B2. Docker client used after close
**Why missed:** The test `test_completed_at_on_state` mocks `containers.get` to raise Exception (simulating dead container), which triggers reconciliation. But the mock Docker client never actually closes, so the use-after-close pattern isn't exercised. Testing this would require a mock that tracks close() state.
**Pitfall coverage:** Covered by existing pitfall #6 (Docker-dependent tests): "Tests that require running Docker containers must be clearly marked." The mock approach is correct but doesn't model the close lifecycle.
**Catch test:** Mock Docker client where `close()` sets a flag, and `containers.get()` raises after close. Verify that `last_logs` is still populated when the container is dead but still queryable.

### B3. Pipeline banner no progress for elevation/OSM
**Why missed:** No automated frontend tests exist (Playwright deferred). Manual test checklist item #4 says "Start an imagery download — banner appears" but doesn't cover elevation/OSM banner behavior.
**Pitfall coverage:** One-off — specific to the banner implementation choice.
**Catch test:** E2E test (Playwright) that starts an elevation pipeline and verifies the dashboard banner shows progress percentage > 0.

### Testing Pitfalls Updates
- None warranted. B1's test gap is specific to the osm_poi lifecycle, not a generalizable pattern beyond "test all type variants."
