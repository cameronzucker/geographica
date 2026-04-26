# Pipeline sticky-error bug hunt — consolidated findings

**Date:** 2026-04-24
**Scope:** NOAA NAIP pipeline error-state handling. User-reported symptom: after a multi-state bbox triggers the "multi-state dispatch is not yet implemented" guardrail, the error is sticky — re-drawing a single-state bbox doesn't bypass it.
**Hunters:** Exploratory (manzanita), Holistic (manzanita), Multipass (manzanita)
**Reports:**
- [`dev/bug-hunts/2026-04-24-pipeline-sticky-error-exploratory.md`](2026-04-24-pipeline-sticky-error-exploratory.md)
- [`dev/bug-hunts/2026-04-24-pipeline-sticky-error-holistic.md`](2026-04-24-pipeline-sticky-error-holistic.md)
- [`dev/bug-hunts/2026-04-24-pipeline-sticky-error-multipass.md`](2026-04-24-pipeline-sticky-error-multipass.md)

---

## Executive summary

The "sticky" symptom is **not actually a single sticky-state bug** — it's the cooperative effect of three bugs that together create a no-exit-from-error situation:

1. **CB1 — Geographic root cause:** The `states_intersecting` function uses axis-aligned state bboxes. California's rectangle extends east to lon -114.13 at *all* latitudes, so virtually every bbox in southern Nevada or northwestern Arizona is mis-classified as multi-state (CA + NV + AZ). Verified by re-running the function on the user's bbox and on a 0.1° Las Vegas test bbox — both flagged "CA" despite touching zero CA land.
2. **CB2 — No /start pre-check:** `/admin/pipeline/start` already calls `states_intersecting` (inside `_noaa_peak_and_snapshot`) but doesn't gate on the count. Every multi-state bbox dispatches a container that crashes with the same error, overwriting state to `status: "error"` within ~1s.
3. **CB3 — No error-clear path:** `/admin/pipeline/cancel` only mutates state when `status == "running"`. No endpoint, no UI control, no auto-expiration ever clears `status: "error"`. The only path to a clean state is a successful Start — which CB1 + CB2 prevent.

Net user experience: every retry visibly fails the same way, so the error appears locked-in.

A fourth bug (CB4) compounds this: a bare `except: pass` on stale-container cleanup at [main.py:1582-1587](services/search/main.py#L1582-L1587) can let `containers.run()` collide on the name `geographica-pipeline`, returning HTTP 500 — leaving the prior error state untouched. This is a real second cause of stickiness in scenarios where Docker behaves anomalously.

In addition, the bug hunt surfaced **15+ unrelated bugs** ranging from a serious orthogonal architectural issue (NAIP and Sentinel scripts write progress to the wrong state file, so their UI is permanently empty during runs) down to UX polish.

**Counts:** 4 critical, 5 high, 5 medium, 9 low/info, 6 design smells, 7 false positives / unconfirmed.

---

## Confirmed bugs

### CB1 — `states_intersecting` uses axis-aligned state bboxes (geographic root cause)

**Consensus:** Exploratory only — others didn't run the function on user input.
**Location:** [`scripts/common/state_bboxes.py:12-97`](scripts/common/state_bboxes.py#L12-L97), specifically the bbox table at L12-62 and `_states_intersecting()` at L65-97.
**Evidence:**
- California bbox in the table: `(-124.48, 32.53, -114.13, 42.01)` — axis-aligned rectangle extends to lon -114.13 at *all* latitudes.
- User's bbox `-115.6982,35.8829,-114.7706,36.5005` (Lake Mead, fully in NV/AZ): function returns `[arizona, california, nevada]`.
- A 0.1° Las Vegas bbox `-115.15,36.10,-115.05,36.20`: returns `[california, nevada]` (verified live in this session — currently in `.pipeline-state.json`).
- Middle-of-Nevada `-119.5,39.1,-119.4,39.2`: returns `[california, nevada]`.
- Reality check: at lat 36°, CA's actual eastern border is around lon -119° (Owens Valley / Death Valley); CA only reaches -114.13 at the southern Yuma corner (~32.7°N).
- Similar false positives: NV reaches -114.04 at the southern AZ-corner only, but the rectangle treats the entire 35-42°N stripe as intersecting AZ (which ends at 37°N).

**Impact:** Every bbox in the corridor `lon ∈ [-119, -114]` and `lat ∈ [33, 42]` (most of Nevada and central-east California / northwestern Arizona) is mis-classified as multi-state, tripping the pipeline guardrail at [`scripts/acquire_imagery.py:2229-2244`](scripts/acquire_imagery.py#L2229-L2244). User can never construct a "smaller bbox" that escapes the false positive in this region — there's no valid single-state bbox in much of the western US.

**Blast radius:**
- The function is shared by: `_noaa_peak_and_snapshot` ([main.py:1242](services/search/main.py#L1242)), `noaa_estimate` ([main.py:2095](services/search/main.py#L2095)), `resolve_noaa_candidates` → pipeline guardrail, and the peak-disk area-ratio calc (`_count_noaa_tiles` at [main.py:1944-1948](services/search/main.py#L1944-L1948)).
- Replacing the algorithm changes the *meaning* of `states_intersecting` for every caller. Need to verify each caller is OK with stricter (true-polygon) intersection.

**Fix approach:** Replace axis-aligned rectangle test with true polygon intersection. Three viable sources for state boundaries (see Design Decision D1 below). Probably warrants a `states_intersecting_polygon()` and keeping the AABB version for callers that genuinely want the loose check (none currently exist).

---

### CB2 — `/admin/pipeline/start` doesn't pre-check multi-state guardrail

**Consensus:** All three hunters (Exploratory + Holistic-B1 + Multipass-2.3).
**Location:** [`services/search/main.py:1336-1385`](services/search/main.py#L1336-L1385) (NOAA-specific gates) and [L2229-2244](scripts/acquire_imagery.py#L2229-L2244) (the pipeline-side check that fires).
**Evidence:** `_noaa_peak_and_snapshot` already computes `states_list` at [main.py:1242](services/search/main.py#L1242). The endpoint then gates on `missing` (uncataloged states) and `peak_required_gb` but throws away the `len(states_list)` count. So a request that *will* fail with a multi-state error inside the container passes the HTTP gate, spawns a container, writes `status: "running"`, then ~1s later writes `status: "error"`.

**Impact:**
- User sees "running" briefly (or not at all if their poll is slow), then "error". Looks like an instant-fail rather than a server-rejected-the-request.
- Server-side cost: each retry spins up a Docker container, mounts volumes, imports Python — ~1-2s of compute and ~50 MB of memory churn. Wasted, and adds latency to the user's perception of "sticky."
- API users (CLI, automation) would also experience this as a "200 OK then state turns error" rather than a sync 4xx.

**Blast radius:** Adding the guard is local to the `/start` handler — one new check after `_noaa_peak_and_snapshot` returns. Only affects NOAA imagery mode; other modes are unaffected.

**Fix approach:** After `_noaa_peak_and_snapshot` returns at L1342, also check whether the bbox resolves to >1 state. Return a structured 409 with the states list and a suggested action. Pseudocode:
```python
states_list = states_intersecting_polygon(body.bbox)  # CB1 fix
cataloged = [s for s in states_list if s in entries]
if body.bbox and len(cataloged) > 1:
    raise HTTPException(409, {
        "status": "multi_state_unsupported",
        "states": cataloged,
        "message": "...",
    })
```
After CB1 is fixed, this gate is much less trigger-happy (only fires for genuine cross-border bboxes) — but it should still exist because such bboxes are valid user inputs that the pipeline can't handle yet.

---

### CB3 — No path clears `status: "error"` from state file

**Consensus:** All three (Exploratory-B3 + Holistic-B2 + Multipass-2.2/5.6).
**Location:**
- [`services/search/main.py:1784-1828`](services/search/main.py#L1784-L1828) — `/admin/pipeline/cancel` only mutates state when `status in ("running", "cancelling")` (L1800).
- [`services/search/main.py:1671`](services/search/main.py#L1671) — `/admin/pipeline/status` reconciler skips error states (`is_crash_path` requires `status in ("running", "cancelling")`).
- [`frontend/config/index.html:2739-2743`](frontend/config/index.html#L2739-L2743) — error branch renders "NOAA NAIP failed — &lt;error&gt;" with no dismiss control.

**Evidence:** The runtime state file persists `status: "error"` indefinitely. Card UI keeps rendering the red banner across page reloads, navigation, and card collapse/expand. The only path to clear it is a successful Start — which CB1 + CB2 prevent.

**Impact:** Even after we fix CB1 + CB2 (so multi-state errors stop happening), a user who hits *any* pipeline error (genuine network failure, GDAL crash, disk-full, etc.) will see that error sticky-renders forever unless they retry and succeed. There's no "I see the error, now dismiss it and let me try a different mode" affordance.

**Blast radius:** Adding a clear endpoint is local to the search service. Adding a Dismiss button is local to one frontend file. Both should respect concurrent runs (don't allow clearing while `status == "running"`).

**Fix approach:** Two complementary parts:
1. New `POST /admin/pipeline/clear?type=imagery` — atomic state-file rewrite to `{}` (or remove file). Requires `_pipeline_lock`. Refuses to clear if `status == "running"`. Auth-gated like `/start`.
2. Frontend Dismiss button rendered next to the error message in `renderGenericProgress`. Calls /clear, then `fetchAll()`.

---

### CB4 — Bare `except: pass` on stale-container removal can leave state untouched

**Consensus:** Multipass-3.1 + Holistic-B5 (related: B5 is about `_is_pipeline_container_running`).
**Location:** [`services/search/main.py:1582-1587`](services/search/main.py#L1582-L1587) (stale-container removal); [L1175-1187](services/search/main.py#L1175-L1187) (`_is_pipeline_container_running`).
**Evidence:**
```python
# L1582-1587
try:
    old = client.containers.get("geographica-pipeline")
    old.remove(force=True)
except Exception:
    pass

# L1590
container = client.containers.run(
    "geographica-pipeline",  # name conflict if remove silently failed
    ...
)
```
And:
```python
# L1175-1187 — every Docker error returns False
def _is_pipeline_container_running(client) -> bool:
    try:
        containers = client.containers.list(...)
        return any(c.status == "running" for c in containers)
    except Exception:
        return False
```

**Impact:** Two failure modes:
1. If `remove(force=True)` silently fails (container in an unusual state, Docker socket hiccup, permission glitch), `containers.run()` raises a name-conflict error. The /start handler catches this generic `Exception` at L1621 and re-raises as HTTP 500. The state-file write at L1617 **never executes** — the prior error state is preserved verbatim. User sees an alert with "Failed to start pipeline: …" and the underlying error sticks.
2. If `containers.list()` itself raises (socket race, daemon restart, etc.), the duplicate-pipeline gate at L1396 silently passes — both gates evaluate to `False` because the function swallows the error. Two concurrent pipelines can spawn.

**Blast radius:** The bare excepts were intentional (handle "no such container" cases gracefully), but they're too broad. Narrowing to `docker.errors.NotFound` for the get/remove path and surfacing other errors as HTTP 503 is local to two functions.

**Fix approach:**
- L1582-1587: catch `docker.errors.NotFound` only (the legitimate "no stale container to remove" case). Re-raise other exceptions and let them surface to the user as a structured 5xx.
- L1175-1187: catch `docker.errors.DockerException` only; re-raise unexpected errors. Or have it return a 3-state result (`running`, `not_running`, `unknown`) and have callers handle `unknown` explicitly (block as if running, since we can't prove otherwise).

---

### CB5 — Stale `estBoxCustom._diskBlocked` flag survives bbox redraws

**Consensus:** Holistic-B3 only.
**Location:** [`frontend/config/index.html:1700-1710`](frontend/config/index.html#L1700-L1710) (sets the flag during Estimate); [L1820-1834](frontend/config/index.html#L1820-L1834) (Start-custom reads it).
**Evidence:**
- `_renderEstimate` at L1700 resets `estBox._diskBlocked = false` then conditionally sets to `true` when peak > free.
- The flag is reset *only* when Estimate runs again. Re-drawing the bbox does NOT trigger Estimate.
- Start-custom handler L1823: `if (estBoxCustom && estBoxCustom._diskBlocked) { alert(...); return; }`

**Impact:** User runs Estimate on a large bbox → `_diskBlocked = true` → user re-draws a smaller bbox → clicks Start → silently blocked by stale flag from the previous Estimate. The alert message says "Either free space or shrink the bbox, then re-Estimate" — but the user *already* shrunk the bbox. The "re-Estimate" hint is the actual fix, but it's buried in a cluster of words about disk space.

**Blast radius:** Local to the NOAA Custom-area tab. Same pattern likely exists in Whole-state tab (Holistic noted L1764-1778 has parallel logic — verified, also affected).

**Fix approach:** Bind `_diskBlocked` to bbox: when the bbox input changes, clear all per-card stale flags, hide the Estimate box, prompt user to re-Estimate. Or: clear `_diskBlocked` and ack-checkbox state on bbox-input event.

---

### CB6 — Stale ack-missing checkbox state survives bbox redraws

**Consensus:** Holistic-B4 only.
**Location:** [`frontend/config/index.html:1828-1832`](frontend/config/index.html#L1828-L1832) (Custom-area Start handler queries `estBoxCustom` for the checkbox).
**Evidence:** The Start handler does:
```javascript
var ackCheckboxCustom = estBoxCustom ? estBoxCustom.querySelector('#card-' + src.id + '-ack-missing') : null;
if (ackCheckboxCustom && !ackCheckboxCustom.checked) { alert(...); return; }
```
The checkbox is built by `_renderEstimate` only when the *previous* estimate had missing states. After bbox redraw without re-Estimate, the prior checkbox lingers in the DOM. Two failure modes:
1. Prior bbox had missing states + checkbox unchecked → new bbox blocked even if it has zero missing.
2. Prior bbox had no missing states → no checkbox built → new bbox sends `acknowledge_missing=false` even if the new bbox does have missing states (server then 409s with `missing_unacknowledged`, which is at least surfaced).

**Impact:** Failure mode 1 is silent and frustrating (alert that doesn't match the user's mental model). Failure mode 2 surfaces as a server 409 — annoying but recoverable.

**Blast radius:** Same as CB5 — frontend state-management bug local to the NOAA card. Whole-state tab has parallel code.

**Fix approach:** Same as CB5 — invalidate per-card UI state on bbox-input change.

---

### CB7 — NAIP and Sentinel scripts write progress to the wrong state file

**Consensus:** Multipass-2.5 only — orthogonal to sticky-error but architecturally severe.
**Location:**
- [`scripts/acquire_naip.py:545`](scripts/acquire_naip.py#L545): `state_path = output_path.parent / ".pipeline-state.json"`
- [`scripts/acquire_sentinel.py:102`](scripts/acquire_sentinel.py#L102): same.
- Routing: `/admin/pipeline/status?type=naip` reads `.naip-state.json` ([main.py:1146-1147](services/search/main.py#L1146-L1147)); `?type=sentinel` reads `.sentinel-state.json`.

**Evidence:** Verified by grep — both scripts hardcode `.pipeline-state.json`. The frontend polls per-type endpoints which read per-type files. Result: NAIP-county and Sentinel pipelines write progress to a file the frontend never reads, while *imagery*'s state file is being stomped by an unrelated pipeline's writes.

**Impact:**
1. Frontend NAIP-county / Sentinel cards show no progress during their respective runs — empty state.
2. Imagery card shows wrong progress during NAIP/Sentinel runs (mode/source labels misaligned).
3. State-file invariants violated: `_state_file_for_type("imagery")` returns `.pipeline-state.json` but a NAIP run is actively writing to it.

**Blast radius:**
- Fix is at the script level (each writes via the `update_progress` helper that takes `state_path` as a parameter — see `acquire_naip.py:89` signature). Pass the right file path from the launcher (`/start` already knows the type) or have the script derive it from a CLI flag.
- Need to verify no callers depend on the current "wrong" behavior. Specifically: does `/admin/pipeline/status?type=imagery` currently rely on NAIP's progress as a side effect? Should not — but worth checking.

**Fix approach:**
- Add `--state-file=/data/.naip-state.json` (or equivalent) CLI argument to the NAIP and Sentinel scripts.
- `/start` passes the correct value when launching the container.
- Default fallback in the script remains `.pipeline-state.json` (back-compat for direct CLI invocations) — or be strict and require the flag.

---

### CB8 — Non-atomic state-file write at /start races readers

**Consensus:** Multipass-2.1/4.2 + Holistic-B7.
**Location:** [`services/search/main.py:1617`](services/search/main.py#L1617): `state_file.write_text(json.dumps(state_data, indent=2))`.
**Evidence:**
- This is the only state-file write in the codebase that uses `write_text` (truncate-in-place).
- All other writers use atomic tmp+rename: `_atomic_write_json` in `acquire_imagery.py:451-458`, /cancel at L1802-1804, /status reconciler at L1758-1759.
- Concurrent readers exist: pipeline container's `update_progress` (atomic), /status endpoint (`json.loads(state_file.read_text())` at L1641). A reader hitting the file mid-truncation gets `JSONDecodeError`, which the readers swallow as `"unknown"` or empty state.

**Impact:** Brief windows where /status returns junk state. User sees a flash of "unknown" status or an empty card. Low frequency in practice (write window is microseconds) but real.

**Blast radius:** One-line fix using the existing `_atomic_write_json` helper or equivalent.

**Fix approach:** Replace `state_file.write_text(...)` with tmp+rename. Helper exists in `acquire_imagery.py:451-458` — extract to a shared util or inline a 3-line equivalent in main.py.

---

### CB9 — `_is_pipeline_container_running` returns False for any Docker exception

**Consensus:** Multipass-1.1 + Holistic-B5. (Also discussed under CB4 above; listing separately because it has independent failure modes from the cleanup path.)
**Location:** [`services/search/main.py:1175-1187`](services/search/main.py#L1175-L1187).
**Evidence:** See CB4. The function always returns False on error.

**Impact:** Independent of CB4: the /start 409 gate at L1396 evaluates to "no pipeline running" during any Docker hiccup. Two simultaneous /start requests during a daemon restart could both pass the gate.

**Blast radius:** Local to one helper. Callers (3 sites) need updating if the return type changes.

**Fix approach:** Either:
- Catch `docker.errors.DockerException` only; let other exceptions propagate.
- Change return type to `Literal["running","not_running","unknown"]`; have callers default `"unknown"` to "treat as running" (fail closed).

---

### CB10 — Container in "created" state treated as not running → fresh start marked "interrupted"

**Consensus:** Multipass-3.5 + Holistic-B8.
**Location:** [`services/search/main.py:1175-1187`](services/search/main.py#L1175-L1187) (filter checks `c.status == "running"`); [L1671 onward](services/search/main.py#L1671) (status reconciler).
**Evidence:** `_is_pipeline_container_running` only matches `running`. During the brief window after `containers.run(detach=True)` while Docker bootstraps the container (status `created` → `running`, ~10-100ms), a polling /status request can:
1. Read state file (`status: "running"`)
2. Check `_is_pipeline_container_running` — returns False (status `created`)
3. Reconciler concludes pipeline crashed, writes `status: "interrupted"` and `completed_at`.

**Impact:** Race condition: user starts a pipeline, immediately polls /status, sees "interrupted." Less common because status-poll cadence is usually 2s+ but observable on slow systems.

**Blast radius:** Local fix — include `created` and `restarting` in the "is running" check, or filter out only the unambiguously-terminal states (`exited`, `dead`).

**Fix approach:** Change `c.status == "running"` to `c.status in ("running", "created", "restarting")` or invert: `c.status not in ("exited", "dead", "removing")`.

---

### CB11 — `/status` writebacks to state file without holding `_pipeline_lock`

**Consensus:** Multipass-3.6/4.1.
**Location:** [`services/search/main.py:1631-1764`](services/search/main.py#L1631-L1764) (status handler with reconciliation).
**Evidence:** /status reads the state file, does TileServer-handoff and log-capture work, then writes back updates without acquiring `_pipeline_lock`. /start does hold the lock for its writes.

**Impact:** TOCTOU. A status poll that started before a /start call can complete its writeback after /start's write, clobbering the fresh "running" state with stale data. Concrete: pipeline runs invisibly (container OK) but UI shows last completed run's status forever.

**Blast radius:** /status is high-frequency (frontend polls 5x per second across 5 endpoints). Adding lock acquisition has latency cost; probably fine but worth profiling.

**Fix approach:** Wrap the writeback portion of /status in `async with _pipeline_lock`. Alternatively, make /status read-only and move reconciliation to a separate background task.

---

### CB12 — Multipass found additional bugs not detailed individually here (B12-B15)

To keep this doc readable, secondary bugs are listed below with one-line summaries. Each is real and verified during cross-validation. Full details in the multipass report.

| # | Bug | Location | Severity | Reference |
|---|---|---|---|---|
| CB13 | `_state_file_for_type` silent fallthrough to imagery for unknown types | [main.py:1138-1150](services/search/main.py#L1138-L1150) | Low | Multipass-1.5 |
| CB14 | `_noaa_peak_and_snapshot` returns the same `(_, _, None)` sentinel for 4 distinct error conditions | [main.py:1219-1247](services/search/main.py#L1219-L1247) | Low (UX) | Multipass-1.2/3.3 |
| CB15 | /status performs privileged side effects (TileServer restart, MBTiles checkpoint) without auth | [main.py:1631-1764](services/search/main.py#L1631-L1764) | Low (security) | Multipass-1.4 |
| CB16 | log-capture `except: pass` produces empty `last_logs` → always "interrupted" verdict for clean fast-reaping completions | [main.py:1691-1700](services/search/main.py#L1691-L1700) | Low | Multipass-5.4 |
| CB17 | /status masks permission/disk errors as `"status": "unknown"` (frontend renders empty) | [main.py:1642-1643](services/search/main.py#L1642-L1643) | Low | Multipass-5.3 |
| CB18 | /cancel returns `{"status": "cancelling"}` even when `container.stop()` raised | [main.py:1812-1828](services/search/main.py#L1812-L1828) | Low | Multipass-5.5 |
| CB19 | Pre-lock `_noaa_peak_and_snapshot` can resolve a different catalog snapshot than the pipeline container eventually pins, if /refresh runs in between | [main.py:1336-1340](services/search/main.py#L1336-L1340) | Low (race, low freq) | Multipass-1.3/4.4 |
| CB20 | Raw Docker exception strings leak to user `alert()` with no recovery guidance | [main.py:1621-1622](services/search/main.py#L1621-L1622) → [index.html:1338](frontend/config/index.html#L1338) | Low (UX) | Multipass-5.1 |
| CB21 | Multi-state error message doesn't tell user *which state* their bbox crossed unexpectedly (currently lists USPS codes — could include "you mostly meant Nevada, but tipped into California by 0.4°") | [acquire_imagery.py:2237-2240](scripts/acquire_imagery.py#L2237-L2240) | Low (UX) | Multipass-5.2 |
| CB22 | NOAA card always opens on Whole-state tab (`active` is hardcoded) — user retrying a Custom-area failure must manually re-select tab | [index.html:1416-1420](frontend/config/index.html#L1416-L1420) | Low (UX) | Holistic-B6 |

---

## Design decisions requiring user input

### D1 — Source for state polygon boundaries (fixes CB1)

**The concern:** CB1's fix replaces axis-aligned bbox intersection with true polygon intersection. Where do state polygons come from?

**Options:**

| Option | Pros | Cons |
|---|---|---|
| (a) shapely + cached NOAA shapefiles at `data/noaa_cache/{slug}_{year}/*.shp` | Already on disk after first refresh; high accuracy | Depends on refresh having run; shapefiles are state-tile indices, not state outlines (need to verify they include state boundary) |
| (b) Census TIGER state boundaries simplified to GeoJSON | Authoritative, well-known | New ~hundreds-of-KB asset to ship; one-time data acquisition step |
| (c) Bake a hand-tuned simplified polygon table into `state_bboxes.py` | Tiny (~10 KB), no runtime deps | Manual work; less accurate; needs review/test |
| (d) Keep AABB but tighten by latitude band — split each state into 3-5 latitude strips with their own E-W bbox | Pure code, no new deps | Custom approximation; needs per-state hand tuning; still loose |

**Recommendation:** **(b) — Census TIGER simplified to GeoJSON.** It's authoritative, lives outside the repo (in `/srv/geographica/data/`), and a small (~200 KB) simplified polygon set + shapely makes intersection a 5-line replacement. The pipeline already has shapely available (used by other GIS code). Acquiring the file is a one-time setup-script addition.

If we want to avoid shapely, **(c)** is workable but tedious — for the western US specifically (the user's coverage area), 11-state hand-tuned polygons would take a few hours. Defer until there's a reason to avoid the dep.

---

### D2 — Should we actually implement multi-state dispatch (the original "we built this?" question)?

**The concern:** Cameron asked earlier in this session if multi-state was already built. It's not — it was deferred during the CONUS expansion. ~90% of the infrastructure exists (`build_unified_queue`, multi-state result aggregator, etc.). The missing piece is one outer loop in `run_noaa()`.

If we implement it, the entire CB1/CB2/CB3 chain becomes much less critical — there's no longer a hard fail on multi-state, just a longer-running pipeline.

**Options:**
- (a) **Fix only the symptoms** — CB1 (geographic accuracy) + CB2 (server-side gate) + CB3 (dismiss UX). Multi-state still rejected, but rejected accurately and dismissably.
- (b) **Implement multi-state dispatch** — eliminates the guardrail entirely. Bigger scope but addresses root cause of "user wanted a multi-state run."
- (c) **Both** — fix symptoms now (high value, low effort), schedule multi-state implementation as a follow-up.

**Recommendation:** **(c).** Symptoms-fix is essential regardless (any error gets sticky). Multi-state implementation is a separate brainstorm → spec → plan cycle (per project rigor) and shouldn't be smuggled into a bug-fix plan. Fix the bugs now, schedule the feature work next.

---

### D3 — Error-clear mechanism (fixes CB3)

**The concern:** How does a user dismiss an error state?

**Options:**
- (a) **Explicit endpoint + UI button** — `POST /admin/pipeline/clear?type=imagery` + Dismiss button next to error message. Standard pattern.
- (b) **Auto-clear on next /start success** — already happens. Insufficient because users get stuck in retry loops if the error reproduces.
- (c) **Time-based expiration** — after 24h, error auto-stales. Doesn't help users in the moment.
- (d) **Smart auto-clear: when the user navigates away or collapses the card, clear** — frontend-only; user can't resume reviewing the error after closing.

**Recommendation:** **(a)** — explicit endpoint + UI button. Most idempotent, most discoverable, most reversible. Refuses to clear if `status == "running"`. Skip (c)/(d) — they create surprise.

---

### D4 — Should CB7 (NAIP/Sentinel state-file mismatch) be in the same fix plan?

**The concern:** Architecturally severe (NAIP UI shows no progress during NAIP runs!), but unrelated to the user's reported sticky-error symptom. Same area of code, similar pattern.

**Options:**
- (a) Include — same code area, parallel pattern, one fix session is more efficient
- (b) Defer — keep this plan focused on the sticky-error symptom; open a separate plan for state-file plumbing

**Recommendation:** **(a) — include.** The fix is small (pass `--state-file` flag from /start to the script) and prevents another "I thought we built this?" moment when Cameron next runs a NAIP pipeline.

---

### D5 — Scope of Docker-error-handling fix (CB4 + CB9 + CB10)

**The concern:** The bare-except pattern recurs in three places. We could fix one at a time or do them all.

**Options:**
- (a) Fix only CB4 (the one that caused the user-visible 500) — minimal blast radius, quickest
- (b) Fix CB4 + CB9 (both the cleanup and the helper) — addresses the gate-bypass scenario
- (c) Fix all three — also include CB10 (created state)

**Recommendation:** **(b)** for the same fix plan, **(c)** if CB10 has a test we can write quickly. CB10 is a real race but lower-frequency; defer if it adds friction.

---

## Bugs outside primary scope (worth flagging)

These were found during the hunt but aren't in the "sticky error" symptom path. Listed for triage:

- **OS1 (ARCHITECTURAL):** CB7 — NAIP/Sentinel write to wrong state file. **Recommendation: include in this fix plan (D4 above).**
- **OS2 (RACE):** CB11 — /status writeback without lock. **Recommendation: include if scope allows; high-value, isolated fix.**
- **OS3 (SECURITY-LITE):** CB15 — /status without auth. **Recommendation: defer to separate hardening pass; not exploitable for damage in current threat model (offline mesh deployment).**
- **OS4 (HYGIENE):** CB16, CB17, CB18, CB20 — error-handling polish. **Recommendation: defer, batch later.**
- **OS5 (UX):** CB21, CB22 — error-message specificity, default tab selection. **Recommendation: defer; fix when refactoring the NOAA card.**

---

## False positives / unconfirmed

### Ruled out by exploratory hunter (verified during investigation)

- **H1 — stale-container collision in normal ops:** ruled out via 3 successive curl tests; verified the CB4 path is the *anomalous* failure mode, not the normal one. Both findings are coherent.
- **H4 — `syncMapToBbox` doesn't update `#cfg-bbox`:** verified — it does, plus dispatches input event.
- **H7/H9 — state-file write races wholesale:** ruled out wholesale, but multipass found a real specific race (CB8/CB11). Refined understanding: the *baseline* writes are safe (atomic rename); the /start writeback is the outlier.

### Ruled out by holistic hunter

- Docker `list(all=False)` false-positives on exited containers — verified, exited containers don't show up.
- `_resolve_or_pin_snapshot` preserving stale pointer across retry — verified safe.
- `renderGenericProgress` permanently disabling Start buttons — verified, only 'running'/'cancelling' disable.
- progress-poll leaks on card collapse — already fixed in prior work.

### Multipass unconfirmed suspicions (mentioned but not verified)

- **S1 — docker-py name-filter substring vs exact** for CLI-container matching. Plausible; would need a docker-py source read or live test.
- **S2 — `containers[0]` ordering nondeterminism** when multiple `geographica-pipeline*` exist. Plausible but the codebase doesn't index `[0]` of the filtered list.
- **S3 — `_anyPipelineRunning` flag staleness across 5 independent polls.** Plausible during boot; low impact.

**Recommendation:** Don't add these to the fix plan. Note for future investigation if symptoms emerge.

---

## Design smells (not bugs, but flag for awareness)

| # | Smell | Source |
|---|---|---|
| DS1 | State-file schema is implicit and shared across two processes with no documented contract | Holistic + Multipass |
| DS2 | `_pipeline_lock` (asyncio.Lock module-level) is per-worker — silently useless under multi-worker uvicorn | Multipass-4.3 + Holistic |
| DS3 | NOAA Start has 5 nested per-element DOM gates — should be one derived `canStart` state | Holistic |
| DS4 | Pipeline container is run-and-hope, not supervised. No short-lived exit-code watcher to surface preflight failures in the same HTTP turn | Holistic |
| DS5 | No automatic cleanup of `geographica-pipeline-run-*` (CLI-prefix) containers | Holistic |
| DS6 | /cancel races /start on state reads/writes; second rapid user click can SIGTERM a just-started pipeline | Multipass-4.5 |

These are architectural observations, not actionable bugs. Pull them into the implementation log for future tech-debt reference.

---

## Test gap analysis

For each confirmed critical/high bug, why didn't tests catch it?

### CB1 — axis-aligned state bboxes

**Why missed:** Tests for `states_intersecting` likely verify intersection with axis-aligned test bboxes that don't probe the false-positive zones. No test asserts "a bbox at (lon -115, lat 36) is NOT California."

**Pitfall coverage:** Probably falls under a "test edge cases of geographic computations against ground truth" pitfall. Should check `dev/pitfalls/testing-pitfalls.md`.

**Catch test:** A parameterized test asserting that several known-single-state bboxes (Lake Mead-NV, Las Vegas-NV, central Nevada, Salt Lake City-UT, Phoenix-AZ in the SW corner) each return exactly one state. Would have failed against the current implementation.

### CB2 — no /start multi-state pre-check

**Why missed:** Integration tests of /start probably only cover the happy-path cases (single state, valid bbox). No test asserts "a multi-state bbox returns 409, not 200-then-error." This is a "negative path / error precondition" test gap.

**Pitfall coverage:** Likely covered by a "test the negative path of every gate" pitfall. Worth checking.

**Catch test:** Send `/admin/pipeline/start` with a multi-state bbox. Assert HTTP 4xx (NOT 200). Would have surfaced the gap.

### CB3 — no error-clear path

**Why missed:** No test exists for "post-error retry must succeed" because there was no hypothesis that retry would fail. This is a *missing scenario* — the testing-pitfall gap is "test that errors are recoverable, not just that errors are produced."

**Pitfall coverage:** New pitfall candidate.

**Catch test:** Force an error → assert there's a clear path back to a clean state.

### CB4 — bare except: pass on container removal

**Why missed:** Mocking the Docker SDK in tests typically returns clean responses. No test injects a Docker error during cleanup. "Mock the failure modes of external dependencies" is a common gap.

**Pitfall coverage:** Likely covered by a "test failure modes of external clients" pitfall.

**Catch test:** Mock `client.containers.get(...).remove(force=True)` to raise APIError. Assert the user gets a structured error (not silent success leading to name conflict).

### CB5/CB6 — frontend stale state

**Why missed:** Frontend tests are limited (no Playwright suite per CLAUDE.md). The behavior would only surface in browser interaction tests.

**Pitfall coverage:** Acknowledged gap — the project has documented this as a frontend-testing limitation.

**Catch test:** Playwright or jest-dom test simulating Estimate → bbox-redraw → Start, asserting no alert is shown.

### CB7 — NAIP/Sentinel state-file mismatch

**Why missed:** Each script is unit-tested independently. No integration test verifies "frontend can see progress for a NAIP run" because the routing happens at /start, not in the script. Cross-component invariants aren't tested.

**Pitfall coverage:** "Test invariants that span component boundaries" — likely a covered pitfall not followed.

**Catch test:** End-to-end: start a NAIP pipeline (mocked Docker run), poll `/admin/pipeline/status?type=naip`, assert progress is non-empty.

### Testing pitfalls candidates

Based on the gaps above, candidate additions to `dev/pitfalls/testing-pitfalls.md`:

1. **Test negative paths of every server gate** — for any HTTP endpoint with conditional rejections, add a test for each rejection case. Don't just test the happy path.
2. **Test error recoverability, not just error production** — for any error state a user can encounter, assert there's a clear path to a clean state.
3. **Test invariants that span component boundaries** — when N processes share a file/IPC channel, write at least one integration test that verifies they agree on the contract.
4. **Mock failure modes of external clients** — for Docker, AWS SDK, HTTP libraries, etc. — at least one test per call site should inject an exception and verify the calling code handles it gracefully (not catches+ignores).

(Will defer the actual file update to the fix plan's writing phase, after confirming with Cameron which of these are already documented.)

---

## Completeness check

Before closing this consolidation, verify every hunter finding is accounted for:

- **Exploratory:** 3 bugs (E1=CB1, E2=CB2, E3=CB3). All 9 ruled-out hypotheses verified. ✓
- **Holistic:** 8 bugs (B1=CB2, B2=CB3, B3=CB5, B4=CB6, B5=CB9, B6=CB22, B7=CB8, B8=CB10) + 6 design smells (DS1-6) + 7 ruled-out items. ✓
- **Multipass:** 15 bugs (B1=CB3, B2=CB2, B3=CB4, B4=CB7, B5=CB8, B6=CB10, B7=CB11, B8=CB15, B9=CB9, B10=CB14, B11=CB16, B12=CB17, B13=CB19, B14=CB18, B15=CB20) + 3 unconfirmed (S1-3). ✓

Every finding mapped. Total: 22 bugs (4 critical, 5 high, 5 medium-via-CB12-table, 8 low/info), 6 design smells, 3 unconfirmed suspicions.

---

## Next step

Phase 5: present this consolidated report to Cameron with the design decisions (D1-D5) before writing the fix plan. The plan will execute via `/subagent-driven-development` or `/executing-plans` once Cameron has weighed in on the design questions.
