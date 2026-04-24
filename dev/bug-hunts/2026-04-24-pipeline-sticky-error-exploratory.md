# Exploratory bug hunt — pipeline sticky error state
**Date:** 2026-04-24
**Agent:** manzanita

## Executive finding

The "sticky error" is not a sticky state-file bug. Both the backend and the frontend correctly allow a fresh `/admin/pipeline/start` to overwrite the error state — I reproduced this via `curl` on the live system and saw the state file overwritten every time, with no 409 from the start endpoint.

The user's "can't bypass it" symptom is caused by a **geographic-reasoning bug** in `states_intersecting()`: it uses axis-aligned bounding boxes per state, so California's bbox extends east to -114.13, Arizona's north edge is 37.00, Utah's south edge is 37.00, and Nevada's east edge is -114.04. The result: nearly every practical southern-Nevada bbox — including the user's Lake Mead / Las Vegas bbox — is classified as multi-state (CA + NV + AZ). The pipeline's `len(candidates) > 1` guardrail then hard-exits with the "multi-state dispatch not yet implemented" error. Every redraw the user tries still intersects multiple state bboxes, so the error *appears* sticky.

Pairs with two process/UX bugs that amplify the confusion (see Bug 2 and Bug 3).

## Confirmed bugs

### Bug 1 — `states_intersecting` uses axis-aligned state bboxes, classifying ~every southern-NV/central-AZ/central-UT bbox as multi-state
- **Location:** `scripts/common/state_bboxes.py:12-97` (STATE_BBOXES + `_states_intersecting`)
- **Called from:**
  - `services/search/main.py:1242` in `_noaa_peak_and_snapshot` (HTTP-layer peak-disk + ack-missing gate)
  - `services/search/main.py:2095` in `noaa_estimate` (UI estimate card)
  - `scripts/acquire_imagery.py:153` via `resolve_noaa_candidates` (pipeline container, the multi-state guardrail that fires the sticky error at L2229-2244)
- **Evidence (runtime, confirmed just now via curl on live stack):**
  - User's bbox `-115.6982,35.8829,-114.7706,36.5005` (Lake Mead; overwhelmingly NV+NW AZ, zero CA land): `states_intersecting` returns `["arizona","california","nevada"]`. CA is a false positive — the user's bbox is entirely east of CA's actual eastern border (~-114.63 in that latitude band), but CA's axis-aligned bbox extends to -114.13.
  - A 0.1×0.1 degree bbox dead in the middle of Nevada (`-119.5,39.1,-119.4,39.2`, ~Carson City) is classified `["california","nevada"]`.
  - A 0.1×0.1 bbox just south of Las Vegas (`-115.15,36.10,-115.05,36.20`, unambiguously Nevada) is classified `["california","nevada"]`.
  - The only Nevada bbox that *doesn't* claim CA is a sliver 0.08 degrees wide between longitudes -114.13 and -114.05, north of latitude 37.00 (to dodge AZ) — approximately a 9 km × 550 km strip along NV's SE border. Effectively no user would ever draw this by accident or intent.
- **Impact:**
  - The pipeline's multi-state guardrail (`scripts/acquire_imagery.py:2229-2244`) fires for essentially every NV bbox, every central-AZ bbox (near UT/CO), every central-UT bbox (near AZ/CO/NV), every NM bbox (near AZ/CO/TX). User sees "bbox intersects N states … multi-state dispatch is not yet implemented" and has no practical way to find a qualifying bbox.
  - The same over-approximation causes `_count_noaa_tiles` (`services/search/main.py:1944-1948`) to attribute phantom tiles to states whose *axis-aligned bbox* overlaps but whose *actual territory* does not. Peak-disk estimates are inflated.
  - `missing[]` in `_noaa_peak_and_snapshot` is similarly polluted — a pure-NV bbox can claim a CA "missing" if CA happens not to be cataloged, triggering an ack-missing checkbox that should never have appeared.
- **How I found it:** Started with the primary claim. `curl`-ed `/admin/pipeline/start` against the live stack with the user's original bbox and three attempted single-state redraws. Every attempt successfully overwrote `.pipeline-state.json` — no frontend or backend sticky behavior. But every attempt *also* crashed inside the pipeline container with the multi-state error, including bboxes unambiguously inside a single state. Traced the guardrail to `resolve_noaa_candidates` → `states_intersecting` → axis-aligned bbox overlap in `STATE_BBOXES`.
- **Fix approach:** Replace (or augment) axis-aligned intersection with shapefile-accurate intersection. The per-state tile-index shapefiles are already cached at `data/noaa_cache/{slug}_{year}/*.shp` (by `refresh_noaa_catalog.py`) and are what `build_state_queue` uses at pipeline execution. Using those (or the coarser Census TIGER state-boundary shapefile) would cut the false-positive rate to near zero. Until that lands, the pipeline's hard `sys.exit(1)` on `len(candidates) > 1` could relax to "pick the single state with the largest overlap ratio, log the others as skipped" — matching the behavior of the existing `missing:[]` ack flow.

### Bug 2 — `/admin/pipeline/start` does not pre-check the multi-state guardrail; every retry spawns a container, writes "running", then crashes
- **Location:** `services/search/main.py:1269-1628` (`/admin/pipeline/start`)
- **Evidence:**
  - L1341-1385: for NOAA the start handler *does* run `_noaa_peak_and_snapshot` to check `missing[]` and peak disk against the axis-aligned state set. But it never checks `len(candidates) > 1`. So the exact condition that will deterministically fail inside the container (`scripts/acquire_imagery.py:2229`) is not guarded at the HTTP layer.
  - I confirmed: posting a bbox that definitely crashes (user's bbox) returns 200 `{"status":"started"}`, flips state to `running`, spawns `geographica-pipeline`, container runs ~1 second, calls `update_progress(status="error", phase="error", error=msg)`, `sys.exit(1)`.
  - From the user's perspective each retry flickers running → error and nothing else; there's no way to tell from the UI whether the bbox is "hopeless" (multi-state under `states_intersecting`) or merely "under-disk" or "missing" etc.
- **Impact:**
  - Error state keeps getting "reset and re-hit" on every click, reinforcing the feeling that the error is stuck. 
  - Wastes Docker resources (spawns a container, pulls image, runs pipeline startup).
  - Logs fill with identical failures.
  - Masks Bug 1's real cause — the user can't distinguish "geography too permissive" from "this specific bbox is unsupported".
- **How I found it:** After reproducing Bug 1, I expected the /start handler to short-circuit. Re-read `_noaa_peak_and_snapshot` and the Start handler carefully: the multi-state condition is *computed* (states_list has len > 1) but never *rejected*. The handler only cares about `missing[]` and `peak_required_gb`.
- **Fix approach:** Move the `len(candidates) > 1` check from `acquire_imagery.py:2229` up into `_noaa_peak_and_snapshot` / `/admin/pipeline/start`, returning a 409 with a structured `status: "multi_state_unsupported"` payload. The frontend can then render a targeted affordance ("Your bbox spans {CA, NV, AZ}. Use the 'Whole state' tab to download one at a time.") instead of the post-hoc error-status message.

### Bug 3 — There is no UI affordance to dismiss an error state; it persists visibly until the next pipeline write
- **Location:**
  - `services/search/main.py:1784-1828` (`/admin/pipeline/cancel`) only transitions `running → cancelling`. Does not clear error states.
  - `frontend/config/index.html:2739-2743` (renderGenericProgress error branch) shows the error message in `completedEl` indefinitely; nothing clears it on bbox change, tab switch, or "I acknowledge this error" action.
  - No `/admin/pipeline/state/clear` endpoint; no frontend dismiss button.
- **Evidence:**
  - The /status endpoint's reconciliation block (`main.py:1669-1761`) only intervenes when `status in ("running","cancelling")` (crash-path) or `status in ("completed","completed_partial")` (handoff-path). `status == "error"` is a terminal state left untouched — correct in isolation but combined with Bugs 1+2, the user sees the same red error banner re-appear within ~2 seconds after every retry and has no way to mark it "understood".
  - In renderGenericProgress, `if (d.status === 'error')` branch (L2739) updates `completedEl` but never adds a "dismiss" control.
- **Impact:**
  - Reinforces the "sticky" perception: the red error banner + the error text in the pipeline status is always present on every page refresh until a brand-new start succeeds.
  - Combined with Bug 1, the user has no path to a *clean* UI state short of restarting services or manually deleting `.pipeline-state.json` on the host.
- **How I found it:** Traced the `_is_pipeline_container_running` + reconciliation paths looking for an auto-clear. None exists. Then checked `/cancel` — it only handles `running → cancelling`. Then scanned the frontend for any explicit dismiss/clear mechanism. None.
- **Fix approach:**
  - Add `/admin/pipeline/clear` (or extend `/cancel`) that accepts a type= and, when status is a terminal error, deletes the state file or marks it `status: "dismissed"`. Frontend wires a "Dismiss" button on the error state; Start-Custom and Start-Whole also implicitly clear prior error state on successful submit (already happens via L1602 state_file.write_text, but user doesn't know this without hitting Start).
  - Better: make an actionable error message. When the multi-state guardrail fires, render a "Try instead:" suggestion listing the three states with one-click "Start whole state for {X}" buttons.

## Unconfirmed threads / suspicious code

- **`_count_noaa_tiles` axis-aligned area-ratio approximation (`main.py:1942-1948`):** Uses the *axis-aligned* state bbox in the denominator and the user-bbox-∩-state-bbox area in the numerator. For any state with a non-rectangular real shape (e.g. California's "L" shape), the ratio undercounts/overcounts tiles depending on where the user bbox lands. Not the sticky-error cause, but a systematic accuracy bug in tile-count estimates. Worth a dedicated pass once Bug 1 is fixed (would be moot if we switch to shapefile-accurate intersection).

- **`_noaa_peak_and_snapshot` treats "no cataloged states" as "no constraint" (`main.py:1246-1247`):** Returns `([], 0.0, None)` when `states_list` is empty. The `/start` handler at L1348 then rejects with 409 "no_catalog". That's correct. But it's a thin invariant — if someone later adds a code path that bypasses the `snapshot_path is None` check, the pipeline would spawn with no catalog resolvable and crash inside `pin_catalog_snapshot()`. Suggest a defense-in-depth check at the start of `pipeline_start` that short-circuits on empty `candidates` as well.

- **`old.remove(force=True)` silently swallows errors (`main.py:1582-1587`):** I confirmed it works for exited containers. But if Docker returns a transient error (e.g., the daemon is slow, container is mid-removal from another process), the bare `except Exception: pass` masks it, and then `containers.run(..., name="geographica-pipeline")` will raise `APIError: Conflict` at L1590, which the outer `except Exception as e` at L1621 turns into a 500. The state file was already set to "error" by the previous pipeline; the new run fails cleanly; the state file stays on the OLD error. Not what the user reported here, but worth noting: if a pipeline retries rapidly (e.g., frontend double-click) and Docker happens to be slow, this could genuinely block a legitimate retry.

- **Frontend `_diskBlocked` and `ack-missing` gates (H5, H6):** I traced these carefully — both are DOM-scoped to `estBoxWhole` / `estBoxCustom` and are wiped on `estBox.textContent = ''` at the top of `_renderEstimate`. They can only persist if the user never clicks Estimate again. In the error state, the card is collapsed after the first Start; re-expanding the card rebuilds the whole body via `renderNoaaBody`, wiping those flags. So sticky, but only within a single card-open session without clicking Estimate — fine for the standard flow.

- **Frontend `_imageryRunning` + `updatePipelineButtons`:** `_imageryRunning = d.status === 'running' || d.status === 'cancelling'` at `index.html:3183`. On error status, this is false, so `_anyPipelineRunning` is false, so the Start button is NOT disabled. Confirmed no sticky-button behavior.

## Ruled out

- **H1 — stale container collision:** Confirmed `old.remove(force=True)` works; I ran three successive starts against the same exited container with no 409. Not the cause.
- **H2 — /start 409 falsely rejecting on state file:** The state-file check at L1401-1407 only triggers on `status == "running" AND container_running`. Error status passes through fine. Confirmed via curl.
- **H3 — `_noaa_peak_and_snapshot` returning `(…, None)` for valid bbox:** Only returns None when catalog missing OR states_list empty (no cataloged states). For the user's bbox with AZ/CA/NV all cataloged, returns a valid snapshot_path. Confirmed.
- **H4 — `startPipeline` reads stale cfg-bbox while user redraws map only:** `syncMapToBbox` (`index.html:2907`) always writes the new bbox into `#cfg-bbox` AND dispatches an input event. Confirmed by reading the mouseup handler.
- **H5/H6 — sticky `_diskBlocked` / ack-missing in DOM:** Both are scoped to the per-card estBox element and are cleared on the next `_renderEstimate` or on card collapse+reopen (which calls `renderNoaaBody` again). Not the cause.
- **H7 — polling race on state file write:** `update_progress` uses a single atomic rename (`_atomic_write_json`) per update. `pipeline_status` writes via `tmp = state_file.with_suffix(".json.tmp")` + `os.replace`. Both atomic.  No observed race.
- **H8 — Custom-area Start uses a different bbox input:** `index.html:1821` reads `document.getElementById('cfg-bbox').value` — the same global bbox. Confirmed.
- **H9 — read-during-write race:** Atomic renames. Not the cause.

## Design concerns (not bugs; flagged per skill instruction)

- **Axis-aligned bboxes for state-overlap reasoning in a geospatial product** is a fragile abstraction that will keep causing bugs until replaced. The shapefiles for accurate intersection already exist on disk (`noaa_cache/{slug}_{year}/*.shp`); not using them is a legacy shortcut that should be paid down.
- **Errors that originate inside the pipeline container are invisible to the HTTP layer until the state file is re-read.** The /start handler should be a more complete gate — every condition that the pipeline script can reject should be mirrored (as close to accurately as possible) in the HTTP handler so the user gets a synchronous 4xx with actionable text instead of an async "running" → "error" flap.
- **No "dismiss error" UX** means stale errors persist indefinitely and the user has to reverse-engineer whether a retry will work. An explicit ack/clear path prevents the confusion in Bug 3.

## Follow-ups for testing-pitfalls.md

Leaving this for the caller to decide, but two candidates worth considering:

1. *Geometric primitives should be tested against real-world edge cases, not only axis-aligned toy inputs.* The `_states_intersecting` function passes trivial tests ("bbox in AZ returns [AZ]") but fails on realistic user inputs where state boundaries aren't axis-aligned. A testing-pitfall entry: "When testing geographic intersection, include a bbox inside a state whose axis-aligned bbox overlaps a neighboring state. If the function classifies that bbox as multi-state, the primitive is wrong — upgrade to shapefile intersection."

2. *"Pipeline crashes inside container" tests should assert that `/admin/pipeline/start` returns the same error the container would.* Today the HTTP handler and the container have drifted: `/start` allows a request the container will deterministically reject. A testing-pitfall: "When a pipeline guardrail fires inside the container, add a matching guard at the HTTP layer and assert both reject the same inputs."
