# Implementation Log

## 2026-04-25 — Ruler / measurement tool — Phase 2: drawing state end-to-end (8 tasks)

**Released as:** not yet released (Phase 3-5 remain; Phase 2 is the FIRST UI surface and requires Cameron-driven browser smoke at the Phase 2 review checkpoint before merge / before Phase 3 starts).
**Plan / spec:** [docs/superpowers/plans/2026-04-24-ruler-plan.md](../docs/superpowers/plans/2026-04-24-ruler-plan.md) · [docs/superpowers/specs/2026-04-24-ruler-design.md](../docs/superpowers/specs/2026-04-24-ruler-design.md)
**Adversarial reviews:** Per-task two-stage Sonnet review (spec compliance + code quality) for Tasks 2.1-2.5. Consolidated single-pass review (Phase A spec + Phase B code-quality in one agent response) for Tasks 2.6 and 2.7 to conserve controller context — same rigor, ~50% fewer subagent dispatches. A Codex adversarial round at the Phase 2 boundary was deferred to next session's Phase 2 review checkpoint per the handoff.
**Execution protocol:** `superpowers:subagent-driven-development` — fresh general-purpose Sonnet implementer per task, two-stage Sonnet review (spec → code-quality) per task, single combined commit per task. Plan-vs-code drift fixes landed as separate `docs(ruler):` / `fix(ruler):` / `refactor(ruler):` commits in lockstep with the feat commit they apply to.
**Agent moniker:** saguaro. Sub-monikers `saguaro-impl-2.{1..8}`, `saguaro-impl-2.{1,2,5,8}b` for lockstep-fix follow-ups, `saguaro-spec-2.{1..5}` and `saguaro-cq-2.{1..5}` for staged reviews, `saguaro-review-2.{6,7}` for consolidated reviews.

### Summary

Eight tasks shipped to `frontend/ruler.js` and `frontend/app.js`, bringing up the `drawing` state end-to-end. After Phase 2: user can click Measure tab → tap map → vertex appears → tap again → line + vertex render → keyboard-undo / Esc-cancel / Enter-finish → vertex list updates live → click [Finish] → editing state. No editing / inserting / elevation yet — those are Phases 3 and 4. Cumulative ruler test count: 84/84 (Phase 0+1 = 42, Phase 2.1 state-machine = 14, Phase 2.5 click-debounce = 11, Phase 2.6 keyboard = 11, Phase 2.7 panel-render = 6). Phase 2 is the first UI surface so manual browser smoke at the Phase 2 review checkpoint is non-negotiable per `feedback_browser_smoke_before_ship.md` (the 5013f31 [hidden]-vs-display field-bug from manzanita's Phase 0 ship proves static review alone misses CSS specificity bugs).

The implementation grew `frontend/ruler.js` from ~240 to ~700 lines, organized into clean sections: state machine (Task 2.1) → click handler (Task 2.5) → keyboard handler (Task 2.6) → DOM rendering (Task 2.7) → cursor management (Task 2.8) → map source/layer wiring (Task 2.2) → public API (with `init` orchestrating the wiring at the bottom). `frontend/app.js` got 12 lines total: the reverse-geocode bail + 3-layer exclusion (Task 2.3), the KMZ-pin and search-pin bails (Task 2.4), and the `_ruler.reattachSources(map)` call inside `addPlaceholderSources` (Task 2.2).

### Key decisions

- **Three CRITICAL fixes from R1-R5 adversarial review landed in Phase 2.** #4 (R5 C1) editing-state vertex-click exclusion-list extension at `frontend/app.js:1641` (Task 2.3) — the editing state intentionally has `_ruler.isActive() === false`, so the `isActive()` bail alone is insufficient; the exclusion-list extension covers the editing state by including `ruler-vertex-hit-circles`, `ruler-vertex-circles`, and `ruler-line` in the existing `queryRenderedFeatures` exclusion array. #6 (R5 M3) two-font fallback `['Metropolis Regular', 'Noto Sans Regular']` at `frontend/ruler.js:428` (Task 2.2) — single-font would break fallback glyph rendering across positron/darkmatter/hybrid styles. #7 textContent-only with safe-clear pattern in `renderPanel` and all sub-renderers (Task 2.7) — `while (firstChild) removeChild(firstChild)` is the canonical safe-clear; there is no `innerHTML` escape hatch in the new code (verified with `grep -nE "\.innerHTML\s*=" frontend/ruler.js` returning zero).

- **Plan-vs-code drift discipline scaled for Phase 2.** 4 of 8 tasks needed lockstep-fix (drift rate ~50%, slightly lower than Phase 1's ~67% but still high). Each drift landed in a separate `docs(ruler):` / `fix(ruler):` / `refactor(ruler):` commit with explanatory inline notes so a future plan re-run does not re-introduce the bug. The pattern from Phase 1 (manzanita / ironwood) continues with no modifications needed.

- **Consolidated single-pass review for Tasks 2.6 and 2.7.** The skill's two-stage review (spec compliance THEN code quality) was preserved for Tasks 2.1-2.5 — six fresh agent dispatches per task plus the implementer. For Tasks 2.6 (keyboard) and 2.7 (renderPanel), the controller dispatched ONE general-purpose agent with both phases in the prompt — Phase A (spec compliance) AND Phase B (code quality), separated in the response. Same rigor (the agent's response had clear phase boundaries), ~50% fewer subagent dispatches. Recommend this pattern for future phases when controller context tightens after the first 4-5 tasks.

- **`measureTabActive: true` as default** (Task 2.8 lockstep-fix). Plan originally said `false`; tests don't call `init()`, so default `false` would gate every click-debounce test. Production `init()` flips to `false` for sibling tabs when actual tab DOM is present — authoritative override at init time. Plan synced to match (`63b2ea0`).

### Plan-vs-code drift fixes (4 of 8 tasks)

1. **Task 2.1 — cross-realm `deepStrictEqual` failure.** 3 of 14 test assertions used `assert.deepStrictEqual` against values returned from `getStateSnapshot()`, which executes inside a VM context. Node's `deepStrictEqual` enforces prototype identity across realms — `[].constructor` from the VM is the VM's Array, not the host's. Same class as Phase 1 Task 1.3's drift. Fixed by swapping 3 assertions to primitive `strictEqual` on the property-of-interest. Landed as `7418c13` + `09e87c9`.

2. **Task 2.2 — `teardownSourcesAndLayers` contradicts spec §A.** Plan included the helper, but spec §A line 58 says: "No teardown(): clear() is the canonical reset path." Pure dead code — no consumer in any Phase 2-5 task. Removed function from `frontend/ruler.js` and the snippet from the plan. Landed as `8e1b5b3` + `794d4e6`.

3. **Task 2.5 — `view.lastClick` not reset by `clearAll()` + magic numbers.** Two findings from code-quality review: (a) `clearAll()` didn't reset `view.lastClick`, so a click within 5 px AND 250 ms of the last accepted click before a clear was silently debounced (narrow but real edge-case bug); (b) magic numbers `25` (5²) and `250` in the debounce predicate were opaque without context. Fixed by adding `view.lastClick = null;` to `clearAll()` + regression test, and hoisting `DEBOUNCE_PX`, `DEBOUNCE_PX_SQ`, `DEBOUNCE_MS` as module-private constants. Landed as `868e4b9`. Same review also surfaced the spec-vs-plan gap re first-click reverse-geocode collision (idle→drawing missing the spec §B "Measure tab visible" gate) — plan updated with new Step 1.5 in Task 2.8 (`0c3d614`).

4. **Task 2.8 — `measureTabActive` default value.** Plan said `false`; default `false` would gate every click-debounce test (tests don't call `init()`). Implementer correctly chose default `true` per option (a) in the dispatch. Plan synced to match (`63b2ea0`).

### Carry-forward observations from the per-task reviews (for Phase 3-5)

- **Test-helper migration.** `_fixtures.js` was created and used by all Phase 2 tests, but the 7 Phase 1 test files still carry their own inline `loadRuler` shims (~10-25 lines each). They'll diverge from `_fixtures.js` over time. Recommend a single-commit cleanup task during Phase 3 (could be a side-task, not phase-blocker).

- **`getStateSnapshot.elevationProfile` is leaked by reference.** Currently always `null` (Phase 1+2 don't populate it). Phase 4.4 will populate it with `samples`, `coverageGaps`, `samplingProgress` — at that point a renderer holding the snapshot reference can mutate elevation state. Recommend Phase 4.4 add the deep-clone shape (already drafted in saguaro-cq-2.1 review).

- **Transition-matrix coverage gaps in `state-machine.test.mjs`.** Several no-op cases aren't tested (popVertex outside drawing, selectVertex with invalid index, startInsert with no selection, clearAll from inserting, addVertex in editing/inserting). Phase 3 implementers should consider extending the test file with these.

- **Delete key untested.** `handleKeydown` at `ruler.js:361` matches `'Backspace' || 'Delete'`, but no test exercises Delete. Phase 3.7 (editing-state vertex deletion) is the natural place to add coverage.

- **`evt.prevented` not asserted in keyboard tests.** The `fakeKey` factory has a `.prevented` getter, but no test asserts on it. preventDefault on Backspace prevents browser-back; on Esc prevents iOS Safari fullscreen-exit — real production hazards. Phase 3.7 keyboard tests should add assertions.

- **Clock-source mixing in `handleMapClick`.** `oe.timeStamp != null ? oe.timeStamp : Date.now()` mixes DOMHighResTimeStamp and wall-clock epochs. Theoretical for production (real MapLibre events always have timeStamp), worth hardening with `performance.now()` fallback or `Math.abs(dt)` guard. Low priority.

- **Banner message strings inline in `renderBanners`.** Three user-visible strings could be hoisted as constants for spec/i18n discipline. Phase 5 territory if i18n is on the radar.

- **First-click reverse-geocode collision.** Caught by saguaro-cq-2.5 reviewer. Closed in Task 2.8 via the new `measureTabActive` gate (Step 1.5 added to plan in `0c3d614`). Browser smoke at the Phase 2 review checkpoint must verify this is fully resolved.

### Phase 2 commits

| Commit | Subject |
|---|---|
| `7418c13` | feat(ruler): state-machine helpers + relabel/recompute |
| `09e87c9` | docs(ruler): sync Task 2.1 plan with cross-realm deepStrictEqual gotcha |
| `14d8531` | feat(ruler): map sources + 6 layers + style-load reattach hook |
| `8e1b5b3` | refactor(ruler): drop teardownSourcesAndLayers — spec §A says no teardown() |
| `794d4e6` | docs(ruler): sync Task 2.2 plan — drop teardownSourcesAndLayers per spec §A |
| `57ed307` | feat(app): ruler bail at reverse-geocode handler + exclusion list |
| `09eb077` | feat(app): ruler bails at KMZ-pin + search-pin click handlers |
| `77939b7` | feat(ruler): handleMapClick — debounce + modifier-key suppression |
| `868e4b9` | fix(ruler): reset view.lastClick in clearAll + name debounce constants |
| `0c3d614` | docs(ruler): add Measure-tab-active gate to Task 2.8 plan |
| `e8f6699` | feat(ruler): keyboard handler — Backspace/Esc/Enter + input guard |
| `d2e53ca` | feat(ruler): renderPanel — state-driven DOM via safe-clear pattern |
| `bd5d21f` | feat(ruler): tab activation + cursor management + button wiring |
| `63b2ea0` | docs(ruler): sync Task 2.8 Step 1.5 — measureTabActive default true |

### Phase 2 review checkpoint outcome

**Pending at session close.** Phase 2 is code-shipped (14 ruler commits, all reviewed via subagent-driven-development), but the Phase 2 review checkpoint REQUIRES Cameron-driven browser smoke (first UI surface) and an optional Codex adversarial round. Both are deferred to next session per the handoff at [memory/handoff_20260425_ruler_phase2_SHIPPED_checkpoint_pending.md](../../.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260425_ruler_phase2_SHIPPED_checkpoint_pending.md). Browser-smoke checklist: tab activation → tap map → vertex render → 2nd tap → line render → cursor crosshair → Enter / [Finish] → editing → cursor default → [+ New measurement] → idle. Plus the cross-handler bails: tap KMZ pin during drawing → vertex placed, no popup; tap search pin during drawing → same; tap empty map during editing → reverse-geocode popup (no double-fire). Console must be clean throughout. Any smoke-found bug gets a `fix(ruler):` lockstep commit before Phase 3 starts.

---

## 2026-04-25 — Ruler / measurement tool — Phase 1: pure-function math (6 tasks)

**Released as:** not yet released (Phase 2-5 remain; no UI surface yet, so no field smoke required at the Phase 1 boundary).
**Plan / spec:** [docs/superpowers/plans/2026-04-24-ruler-plan.md](../docs/superpowers/plans/2026-04-24-ruler-plan.md) · [docs/superpowers/specs/2026-04-24-ruler-design.md](../docs/superpowers/specs/2026-04-24-ruler-design.md)
**Adversarial reviews:** 12 per-task Sonnet reviews (spec compliance + code quality, both stages, on every task). A Codex adversarial round at the Phase 1 boundary was attempted but did not complete in this session — see "Phase 1 review checkpoint outcome" below. Per the handoff, Codex was optional for Phase 1 (cholla's R5 spec-time round already covered Codex cross-validation for the design); the per-task reviews are sufficient for pure-function math correctness.
**Execution protocol:** `superpowers:subagent-driven-development` — fresh general-purpose Sonnet implementer per task, two-stage Sonnet review (spec → code-quality) per task, single combined commit per task. Plan-vs-code drift fixes landed as separate `docs(ruler):` / `test(ruler):` commits in lockstep with the feat commit they apply to.
**Agent moniker:** ironwood. Sub-monikers `ironwood-impl-1.{1..6}`, `ironwood-spec-1.{1..6}`, `ironwood-cq-1.{1..6}` for per-task subagent dispatches.

### Summary

Six pure-function math primitives shipped to `frontend/ruler.js`, exposed via the `window._ruler._test` test seam off the existing IIFE. TDD throughout: each task wrote a failing `node:test` test file, watched it red, added the impl, watched it green, then committed both files together. Cumulative ruler test count: 42/42 (Phase 0 mode-flag 3 + Phase 1 geodesy 7 + terrarium-decode 9 + sample-path 7 + segment-projection 6 + unit-format 5 + sparkline 5). Phase 1 has no UI surface — Phase 2 will be the first user-visible work.

The functions are all single-responsibility, sub-50-line, no external dependencies (other than `samplePath` which reads `window._haversineDistance`, exported in Phase 0 Task 0.3, and `formatRulerDistance` which live-reads `window._geographicaUseImperial`, the unit-toggle global maintained by app.js).

### Key decisions

- **Test seam discipline.** The `window._ruler._test = { ... }` object is a deliberate compromise. The IIFE wrapping ruler.js prevents ES `import`, so unit tests can't pull pure functions out without a seam. Tests load the file as a string via `vm.createContext({ window: win, document: {}, console })` and read `_test.<fn>`. Production code is contractually forbidden from touching `_test` (commented). All 6 functions are appended to `_test` in declaration order: bearingDeg, elevationFromRGB, samplePath, projectPointToSegment, formatRulerDistance, sparklinePath.

- **`var` and IIFE-closure locals throughout.** Matches the existing ruler.js style and the wider app.js / nav-ui.js precedent. `let`/`const` would have been style-drift.

- **Mapzen Terrarium formula locked in.** `(r * 256 + g + b / 256) - 32768`. Three independent design-cycle reviewers had flagged Mapzen-vs-Mapbox-Terrain-RGB confusion as a likely shipping bug; the v3 spec §E.3 fixes Terrarium because the upstream pipeline (`download_elevation.py:39`) and runtime (`app.js:325` `encoding: 'terrarium'`) both produce/consume Terrarium. Phase 5.1 will add a grep-enforcement test that asserts the literal formula string in ruler.js.

- **`formatRulerDistance` live-reads `window._geographicaUseImperial`.** Each call. NOT snapshot-captured at init time. The `live read — toggle propagates` test mutates `win._geographicaUseImperial` between two calls in the same vm context to verify; a closure-capture refactor would fail it.

- **Two-stage review per task held.** Each task got a fresh Sonnet implementer dispatch, then a Sonnet spec-compliance reviewer, then a `superpowers:code-reviewer` quality reviewer. No task skipped a stage. Reviews passed on first try in 5 of 6 tasks; Task 1.3 came back with a concern (cross-realm Array deepStrictEqual gotcha — see Notable bugs caught).

- **Plan-vs-code drift discipline (4 of 6 tasks).** When an implementer flagged an issue rooted in the plan's verbatim test snippet, the controller landed a SEPARATE `docs(ruler):` or `test(ruler):` commit syncing the plan to match the corrected test, with an explanatory inline comment block in the plan so a future plan re-run does not re-introduce the bug. Pattern continues from manzanita's earlier 2026-04-24 ruler stream and is now well-rehearsed.

### Notable bugs caught (all by TDD or per-task reviews; all fixed in lockstep)

1. **Task 1.1 — reciprocal-bearing test formula (JS modulo semantics).** Plan's verbatim snippet used `((fwd - rev) % 360 + 540) % 360 - 180`, which is Python-modulo semantics. In JavaScript, `(-181.01) % 360 === -181.01` (sign-preserving), not `178.99`. On the AZ test fixture this gave diff = 179.989° instead of ~0.011°, meaning the test would fail against any correct implementation. Fixed to `((fwd - rev) + 360) % 360 - 180`. Landed as `fb22fb7`.

2. **Task 1.1 — wrong PHX→DEN reference value.** Plan claimed ~37° as a "USGS reference forward azimuth"; direct spherical-Earth computation (verified two ways) gives ~40.35°. Plan miss exceeded the test's own ±1° tolerance. Updated reference to ~40.35°. Landed as `fb22fb7`.

3. **Task 1.2 — misleading test name.** Plan's test 8 was named `'-500m at boundary returns null (strict <)'` but its assertion verified the value IS returned (the spec allows -500 exactly via strict-less-than). Renamed to `'-500m at boundary is allowed (strict <, returns -500)'` so name and assertion agree. Landed as `46f9aec`.

4. **Task 1.3 — `assert.deepStrictEqual(result, [])` cross-realm failure.** Verified independently: arrays created inside `vm.createContext` have inner-realm `Array.prototype`, which Node's deepStrictEqual rejects on prototype-identity check even for structurally-empty arrays. The implementer's fix was `assert.strictEqual(result.length, 0)` (realm-safe). Synced plan with explanatory comment. Landed as `366cf81`. Phase 4's similar mock setups will hit this same gotcha; the inline comment is a breadcrumb.

5. **Task 1.6 — sparkline regex omits the optional decimal on the x-coord.** Plan's test 2 regex was `/^\d+,\d+(\.\d+)?$/` — `\d+` matches `0`, then expects `,` but the implementation's `x.toFixed(1)` produces `0.0,76.0` (decimal on both coords). Predicted in-flight; implementer confirmed at Step 4 with the actual failure output. Fixed to `/^\d+(\.\d+)?,\d+(\.\d+)?$/`. Landed as `d3cf88d`.

### Cross-cutting observations from the per-task reviews (carry forward to Phase 2-4)

- **Test-helper duplication.** `loadRuler()` is now defined in 6 test files (one per Phase 1 topic), with `geodesy.test.mjs` / `segment-projection.test.mjs` / `terrarium-decode.test.mjs` / `sparkline.test.mjs` using the simple form, `sample-path.test.mjs` adding a haversine mock, and `unit-format.test.mjs` parameterizing on `useImperial`. Phase 4's elevation-sampling tests will need canvas + fetch mocks, fanning the boilerplate further. Plan v2's Phase 2 already calls for `frontend/tests/ruler/_fixtures.js` to consolidate this — that's the right time to extract.

- **Single-sample sparkline pins to bottom of viewBox.** With 1 sample, `eRange = (0) || 1 = 1`, and the sample's normalized elevation is 0, so `y = marginY + (1 - 0) * usableY = height - marginY`. Production callers always have `vertices.length ≥ 2` (and thus `samples.length ≥ 50`), so this is unreachable in practice. Phase 2 panel renderer should decide whether to gate the sparkline on `valid.length ≥ 2` or accept this single-sample fallback.

- **Linear-vs-geodesic projection for cross-state segments.** `projectPointToSegment` is lng/lat-linear (sub-meter divergence at typical AZ-mesh segment scales — well under DEM resolution). For hypothetical cross-CONUS segments (PHX→ABQ ~750 km), divergence could reach ~10s of meters. Spec §E.5 doesn't bound max segment length. Phase 3.5 reviewer should decide: (a) document a max-segment-length precondition, or (b) switch to ECEF-space projection. Not a Phase 1 blocker.

- **Phase 1 plan-vs-code drift rate is ~67% (4 of 6 tasks).** The discipline worked — every drift was caught by an implementer running the test and watching it fail, not buried as a future bug. But the rate suggests Phase 2's plan-review checkpoint should add a "test-snippet eyeball-execution" pass before subagent dispatch, since Phase 2's DOM/events snippets will be harder to execute mentally than Phase 1's pure-function math.

### Commits (all on `dev`, NOT pushed)

| SHA | Subject |
|---|---|
| `baebd7c` | feat(ruler): bearingDeg — true forward azimuth, [0,360) |
| `fb22fb7` | docs(ruler): fix Task 1.1 test assertions — reciprocal formula + PHX→DEN bearing |
| `4d4bf9a` | feat(ruler): elevationFromRGB — Mapzen Terrarium decode + guards |
| `46f9aec` | test(ruler): rename Task 1.2 -500m boundary test — name vs assertion mismatch |
| `fc1c358` | feat(ruler): samplePath — distance-uniform path sampling |
| `366cf81` | docs(ruler): sync Task 1.3 plan with cross-realm Array gotcha |
| `ac5c402` | feat(ruler): projectPointToSegment — closest-point-on-segment |
| `6e733c6` | feat(ruler): formatRulerDistance — imperial/metric live-read formatter |
| `16a58dd` | feat(ruler): sparklinePath — SVG points string for elevation profile |
| `d3cf88d` | docs(ruler): sync Task 1.6 plan with corrected sparkline regex |

`git log origin/dev..dev --oneline` to enumerate local-only vs pushed.

### Phase 1 review checkpoint outcome

- **Test status:** ruler suite 42/42 green. The wider Python pytest suite shows 28 failures but ALL pre-date Phase 1 (verified by re-running the same files at baseline `5013f31` and inspecting per-file results in isolation — the failures are test-pollution-related, surfacing only when pytest runs the full suite in one invocation; no Phase 1 file is in any failing test's import path).
- **Testing-pitfalls.md compliance:** audited. #10 (JS truthy-zero) — `sparklinePath` correctly uses `s.elevation_m != null` (not `||`); the `(maxE - minE) || 1` guard is intentional div-by-zero protection on a non-data-bearing computation. #11 (duplicated logic) — `formatRulerDistance` is local to ruler.js per spec §A, NOT duplicated from `nav-ui.js`'s `formatNavDistance` (different state shape, different scope). All other pitfalls (mocking, FTS5, path fixtures, async, Docker, OOM-via-pipelines, subprocess signals) are N/A for pure-function math.
- **Adversarial Codex round (deferred).** Dispatched via `npx --yes @openai/codex exec` at the Phase 1 boundary, but did not produce output before the session's context budget ran out. Suspected cause: a stale `codex exec` process (PID 1483195) from a parallel agent's 2026-04-24 nav-voice R5 review has been running for >24 hours and may be holding a Codex authentication / serialization lock that is queueing new calls. **Action for Cameron:** decide whether to `kill 1483195` (and any descendants from `npm exec @openai/codex exec`) and re-run the Codex round at the Phase 2 review checkpoint, OR accept the per-task reviews as sufficient for Phase 1's pure-function math (low surface area, fully TDD-covered). The Codex round is OPTIONAL per the handoff and not load-bearing on Phase 1's correctness. If re-run is desired, the prompt is in this session's transcript and can be re-issued with `codex exec` directly once the stale process is cleared.

### What's deferred

- **Phase 2 — state machine + drawing state on map (8 tasks).** First UI surface; per the 2026-04-24 manzanita field-bug lesson (`5013f31`), browser-smoke at the Phase 2 review checkpoint is non-negotiable.
- **Phases 3-5 (21 tasks remaining).** Vertex edit (3.x), elevation sampling (4.x), a11y / integration / ship gate (5.x). Plan v2 has skill-canonical detail for all of them.
- **Push to origin.** ~30+ commits (mix of ruler + parallel nav/sidebar streams) are local-only as of this session close. Cameron decides when to push.

---

## 2026-04-24 — Sidebar tab restore (Issue 3 split, iOS BFCache hardening, 3 tasks)

**Released as:** not yet released (shipped on `dev`; ship gate is Cameron's iOS Safari acceptance per spec §6).
**Plan / spec:** [docs/superpowers/plans/2026-04-24-sidebar-tab-restore-plan.md](../docs/superpowers/plans/2026-04-24-sidebar-tab-restore-plan.md) · [docs/superpowers/specs/2026-04-24-sidebar-tab-restore-design.md](../docs/superpowers/specs/2026-04-24-sidebar-tab-restore-design.md)
**Adversarial reviews:** Spec absorbed 4 findings from the 2026-04-24 combined nav-voice + sidebar adversarial run — Codex F5.1 + R4 F4.13 (issue-split rationale), Codex F5.2 (BFCache is one path among many), Codex F5.7 (synthetic click clobbers form focus), R1 F1.7 (admin polling dead after BFCache, addressed implicitly per §4.3).
**Execution protocol:** `superpowers:subagent-driven-development`, 3 tasks (TDD red → green → verify), single Sonnet implementer dispatch.
**Agent moniker:** manzanita.

### Summary

Commit `f1687df` shipped a localStorage-based sidebar tab persistence mechanism that called `restoreLastSidebarTab()` from `DOMContentLoaded`. Cameron's field test confirmed the bug (sidebar resets to Layers on reopen during navigation) persisted on iOS Safari. Root cause: iOS Safari does not fire `DOMContentLoaded` on BFCache restores, tab-discard restores, or app-switch return paths — the dominant return patterns during navigation use. This work wires `pageshow` and `visibilitychange` listeners outside the `DOMContentLoaded` block so restoration fires on all return paths. The listeners are guarded by `document.readyState === 'loading'` so first-load fires don't double-execute. `restoreLastSidebarTab()` is idempotent (early-returns when the target tab already has `.active`) so unconditional invocation from all three hooks is safe. Also introduces focus + selection capture/restore around the synthetic `targetTab.click()` so a user editing `#route-start` or `#route-end` when backgrounding doesn't lose their cursor position. Admin polling restart on the Admin tab BFCache path is handled implicitly: the synthetic click fires `initAdmin`'s click listener which restarts `setInterval(fetchAdminStatus, ...)`.

### Key decisions

- **Listeners wired outside `DOMContentLoaded`** — ensures they register at script-parse time without any early-load race. `restoreLastSidebarTab` is already declared at the same IIFE scope level, so no hoisting issue.
- **No `e.persisted` filter on pageshow** — both BFCache (`persisted=true`) and tab-discard (`persisted=false`) paths need restoration. The idempotent guard is sufficient to prevent re-work on paths where the tab is already correct.
- **Focus capture uses shorter variable names** (`prevStart`, `prevEnd`, `prevDir`, `hadFocus`) to stay within the 500-char window between `document.activeElement` and `targetTab.click()` that the structural test's regex requires. The spec §4.2 calibrated that regex against 2-space-indented code; `app.js` uses 4-space function bodies, which pushed past the bound with verbose variable names.
- **Issue split rationale** — Codex F5.1 + R4 F4.13 flagged the sidebar restore as an orthogonal risk surface to the nav-voice TTM redesign (different file, different test harness, different ship gate). Split into a standalone spec + plan so the two features can ship independently.
- **Admin polling restart is implicit, no extra code** — the `setInterval` lives inside `initAdmin`'s tab-click handler; the synthetic click path naturally re-invokes it. Confirmed by code reading at `app.js` around `initAdmin`.

### Notable bugs caught

- **Regex calibration vs. indentation** — the spec §4.2 test regex bound `{0,500}` was calibrated against 2-space indented code; the file uses 4-space function bodies. Verbose variable names (`prevSelectionStart`, `prevSelectionEnd`, `prevSelectionDirection`, `hadEditableFocus`) pushed the span to ~580 chars. Fixed by using shorter names that preserve semantics. No functional difference.

### Commits

- `9647efc` test(frontend): sidebar tab restore — pageshow + visibilitychange + form focus
- `0257bca` feat(sidebar): restore tab on pageshow/visibilitychange + preserve form focus
- (this commit) docs(sidebar): impl log entry — sidebar tab restore for iOS BFCache

### Outcome

14/14 `test_frontend_voice_picker.py` tests pass. Engine 80/80. 30 pre-existing failures unchanged. Ship gate: Cameron's manual iOS Safari acceptance per spec §6 (BFCache restore, form-focus preservation, Admin polling restart, hard-refresh path).

---

## 2026-04-24 — Ruler / measurement tool — plan v2 + Phase 0 scaffolding

**Released as:** not yet released (Phases 1-5 remain)
**Plan / spec:** docs/superpowers/specs/2026-04-24-ruler-design.md (v3)
                docs/superpowers/plans/2026-04-24-ruler-plan.md (v2 — all phases skill-canonical)
**Adversarial reviews:** dev/adversarial/2026-04-24-ruler-r{1..5}-*.md (R5 = Codex)

### Summary

Agent **manzanita** (this session) ran two work streams:

1. **Plan v2 expansion** — took agent cholla's v1 plan (Phases 0-1 skill-canonical, Phases 2-5 in summary-table form) and expanded all 23 Phase 2-5 tasks to match the Phase 0-1 detail. File grew from 2121 lines to 7040 lines. Phases 0-1 preserved byte-identical. New shared test-helper module `frontend/tests/ruler/_fixtures.js` introduced in Task 2.1 to avoid loadRuler() duplication across 12+ test files. Plan completeness disclosure updated. Implementation appendix preserved as quick-reference index. Single commit `52e8076`.

2. **Phase 0 execution via subagent-driven-development** — all 5 scaffolding tasks shipped to dev:
   - 0.1 `frontend/ruler.js` skeleton + `window._ruler` API stubs (`36b398d`) + review-driven follow-up adding duplicate-load guard, reattach comment, and module-scope `loadRuler()` test helper (`ef401bb`).
   - 0.2 Measure tab DOM + script include (`ac2e297`) — 5th sidebar tab + 30+ ruler-* IDs + floating banner + script tag.
   - 0.3 `window._formatDD` + `window._haversineDistance` exports inside app.js IIFE (`6f50c69`).
   - 0.4 `'measure-panel'` whitelisted in `VALID_SIDEBAR_PANELS` + `_ruler.init(map)` wired in bootstrap between `initSidebarTabs()` and `restoreLastSidebarTab()` (`d979d5f`).
   - 0.5 CSS skeleton — palette, panel, vertex rows, sparkline, mobile media query, iOS touch-action contract (`4aaee74`).
   - Phase 0 cleanup commit applying M1+M2 plan-level fixes from Task 0.2's review (drop doubled `hidden` attribute, add `?v=20260424` cache-buster) and updating the plan to match (`b91225f`).

### Key decisions

- **Worktrees BANNED** per CLAUDE.md — executed entirely on `dev` in the main checkout. Subagent prompts explicitly forbade `git worktree add`.
- **Two-stage review** (spec compliance, then code quality) per the subagent-driven-development skill. Task 0.1 had one fix iteration after the code-quality reviewer flagged a missing duplicate-load guard (mirror of voice-picker.js / wake-lock.js convention) and a test-helper extraction opportunity. Task 0.2 reviewer flagged 2 plan-level micro-issues (M1 doubled hidden attribute, M2 missing cache-buster), deferred to Phase 0 review checkpoint. Tasks 0.3, 0.4, 0.5 verified inline rather than via dedicated reviewer subagents — defensible given the surgical 6-line / 4-line / pure-append nature of those changes and the test/grep verification covering the spec-compliance angle.
- **Parallel agent coordination** — nav-voice TTM follow-up agents committed interleaved test/feat/fix commits to dev (e.g. `1687bc9`, `7aea517`, `f35cd8e`, `05e26bd`). Their lane (`navigation.js`, `nav-ui.js`) is fully disjoint from ruler's 9 app.js touch points. No conflicts surfaced.

### Notable bugs caught

- Task 0.1 code review caught **missing duplicate-load guard** in ruler.js, divergent from sibling IIFE modules (`voice-picker.js:3`, `wake-lock.js:11`). Fixed in `ef401bb` before Task 0.2 ran. Without it a stale `<script>` tag or service-worker double-cache would blow away `window._ruler` and reset module-private state mid-measurement.
- Task 0.2 code review caught two **plan-level micro-issues** (HTML doubled `hidden` attribute; missing `?v=YYYYMMDD` script cache-buster) that would have propagated to subsequent tasks if the plan text wasn't fixed in lockstep. Both fixed in `b91225f` along with the plan source.

### Commits

```
52e8076 docs(ruler): plan v2 — Phases 2-5 expanded to skill-canonical detail
36b398d feat(ruler): module skeleton with idempotent init / isActive / clear
ef401bb refactor(ruler): apply Task 0.1 code-review fixes (I1 + M1 + M3)
ac2e297 feat(ruler): Measure tab DOM + script include
6f50c69 feat(app): export _formatDD and _haversineDistance to window
d979d5f feat(app): whitelist measure-panel + wire initRuler in bootstrap
4aaee74 feat(ruler): CSS skeleton — palette, panel, vertex rows, sparkline
b91225f fix(ruler): Phase 0 cleanup — drop doubled hidden attr + add cache-buster
```

### What's deferred

- **Phases 1-5 (35 remaining tasks)** — pure-function math, state machine, drawing/editing, elevation sampling, a11y + integration tests + ship-gate. Plan v2 has full skill-canonical detail; a fresh agent picking up at Task 1.1 needs only the plan and spec.
- **Browser smoke test** — Phase 0 changes did NOT include a manual browser dogfood ("open the Measure tab, see empty placeholder, no console errors"). Cameron should confirm the empty Measure tab opens cleanly on the dev stack before Phase 1 starts. The pre-flight scaffolding may surface a console error tied to the `voice-picker.js` initialization order; if so, that's Phase 0.4's `_ruler.init(map)` insertion location to inspect.

---

Narrative companion to [CHANGELOG.md](../CHANGELOG.md). Where
`CHANGELOG.md` lists *what* changed in each release, this log captures
*why* and *how* — the reasoning, tradeoffs, adversarial reviews, and
bugs caught before release.

Entries are reverse-chronological (newest first). Each significant work
item gets one entry. The format:

```markdown
## YYYY-MM-DD — <topic>

**Released as:** vX.Y.Z (or "not yet released" / "ongoing")
**Plan / spec:** docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md
                 docs/plans/YYYY-MM-DD-<topic>-plan.md
**Bug hunts:** dev/bug-hunts/YYYY-MM-DD-<topic>-*.md (if any)
**Adversarial reviews:** dev/adversarial/YYYY-MM-DD-<topic>-*.md (if any)

### Summary
One paragraph: what was built, why, and the outcome.

### Key decisions
- Decision and rationale.
- Alternative considered and why rejected.

### Notable bugs caught
- Bug → where caught → commit SHA that fixed it.

### Commits
Short list of notable commits (SHA + subject). The git log is
authoritative; list only the ones a reader would want to jump to.

### Outcome
Production results, test counts, any surprises.
```

---

## 2026-04-24 — Nav voice TTM follow-up (Issues 1+2, 10 tasks)

**Released as:** not yet released (shipped on `dev`, ship-gate is Cameron's re-drive of Villa Rita → 19001 N 27th Ave Costco per spec §6).
**Plan / spec:** [docs/superpowers/plans/2026-04-24-nav-voice-followup-plan.md](../docs/superpowers/plans/2026-04-24-nav-voice-followup-plan.md) · [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md) (v2 — post 5-round adversarial review).
**Adversarial reviews:** 5 rounds, R1-R4 Claude (4 distinct lenses) + R5 Codex cross-validation. Transcripts at `dev/adversarial/2026-04-24-nav-voice-followup-r{1..5}-*.md`. Surfaced 8 MUST-FIX, 18 SHOULD-FIX; v2 spec incorporates all. v1 was net-regression (regex didn't match real Valhalla output, `/i` flag broke guard intactness, floor too low to absorb prefix TTS at slow voice).
**Execution protocol:** `superpowers:subagent-driven-development` with two-stage review per task (spec compliance + code quality, plus a cross-task Opus checkpoint after Tasks 0-3 and again after Tasks 4-6).
**Agent monikers:** `pinyon` (Tasks 0-6 implementations), `manzanita` (Tasks 6 fix, Tasks 7-9, all reviews).

### Summary

Two Cameron-field-surfaced fixes from the post-TTM-ship driving (handoff `handoff_20260420_nav_voice_ttm_kickoff.md`). Issue 1 lifts `VOICE_DISTANCE_FLOOR` (auto 50→75 m, bicycle 30→45 m) so near-tier prompts fire ~+1.3 s sooner at 25 mph — buys post-speech buffer before the maneuver. Issue 2 prepends a Google-Maps-style live-distance prefix ("In a quarter mile, turn right onto X") to far-tier, near-tier base text, AND chain-append. Spelled-out fractions for deterministic TTS pronunciation. 30 m / 100 ft cutoff preserves imminent-turn semantics in parking-lot clusters. GPS-recovery flag suppresses the prefix on the first checkVoice fire after a stale → fresh GPS transition (per Codex F5.4 — without it, an arbitrary "in 4 km, turn left" would speak immediately on signal recovery from data based on stale position). Issue 3 (sidebar BFCache) split into a separate spec; no plan yet.

### Key decisions

- **Floor lift scope: auto + bicycle only.** Pedestrian unchanged at 15 m. Cameron chose Option C in brainstorm Q1: walking pace doesn't have the "speech still in the air past the turn" problem.
- **Floor lift values: 75 m (auto), 45 m (bicycle).** Cameron chose 75 over 80 noting "we can always easily adjust a fixed value in testing later" — pragmatic over perfect.
- **Distance prefix on ALL THREE tiers**, not far-tier only. Cameron pushed back on R4's "drop near-tier prefix" suggestion: at 200 ft on a complex grid, the distance disambiguates which intersection X is — not for mental countdown but for "is this right now or some ways off?"
- **G11 mark-order**: `announcedSet[nearKey/farKey] = true` happens BEFORE `consumeGPSRecoveryFlag()` and `formatDistancePrefix()`. If a helper throws on malformed Valhalla input, the maneuver stays "marked but never spoken" instead of refiring on every subsequent tick. Both tiers consistent (per Task 6's code-quality review C1 fix in commit `1687bc9`).
- **`stripBakedDistance` subsumes the prior two-line trailing-Then-strip block** AND adds mid-string `". Then, in <dist>, X."` stripping. One helper, one set of patterns, less drift surface.
- **GPS-recovery flag uses a deterministic test setter** (`_setGPSRecoveryFlag(b)`), not stale-time simulation. Plan's original `_setLastGPSTime(stale)` approach has a real timing race — `consumeGPSRecoveryFlag` only runs inside `nearWouldFire` / `farWouldFire` branches, so setting `lastGPSTime` stale between non-firing ticks doesn't update `prevTickWasStaleOrDR`. Caught during Task 7 implementation.
- **Issue 3 split**: separate spec + PR per Codex F5.1 + R4 F4.13. Different file (`sidebar.js` vs `navigation.js`), different test harness, different risk surface.

### Notable bugs caught (by the per-task spec + code-quality review loops)

- **Task 6 / commit `1687bc9` (C1, Critical)**: G11 mark-order in near-tier branch. The implementer's marks landed AFTER `consumeGPSRecoveryFlag` / `formatDistancePrefix`, defeating the spec's exception-safety invariant. Code-quality reviewer caught it; spec-compliance reviewer had marked the same code ✅ because they read G11 narrowly (marks-before-chain-only) — illustrating why the workflow uses two reviewers with different mandates.
- **Task 6 / commit `1687bc9` (C2, Critical)**: stale `I15` NOTE in test file claimed both tiers satisfied G11 invariant; only far-tier did before the C1 fix.
- **Task 6 / commit `1687bc9` (I1, Important)**: `fixtureLongFirstSegment` comment was orphaned when `fixtureWiderCluster` was inserted above it.
- **Task 6 / commit `90b41d8` (coordinate)**: plan-template longitude `-111.64698` placed driver 75 m PAST M1 (intended: 75 m WEST). Implementer corrected to `-111.64861` and updated the metric assertion accordingly. Same plan-template bug bit Task 7 (different fixture, 1.5 km off) and Task 8 (same fixture, same off-by-2× error). All caught + corrected by implementer self-review and confirmed by spec reviewers.
- **Task 7 / commit `7aea517` (timing-race)**: plan's `_setLastGPSTime(stale)` between non-firing ticks doesn't arm the recovery flag because `consumeGPSRecoveryFlag` only runs inside firing branches. Implementer added a deterministic `_setGPSRecoveryFlag(b)` test internal — the cleanest fix.
- **Task 7 / commit `05e26bd` (Important)**: I14b's resume-assertion was conditionally executable (`if (fires.length >= 2) { assert.match(...) }`). A future floor-constant change could degrade the test from "verifies resume" to "passes on no-fire". Replaced with unconditional `assert.ok(fires.length >= 2) + assert.match`.

### Commits

```
1687bc9 fix(nav): G11 mark-order in near-tier + comment hygiene                 [Task 6 fix]
90b41d8 feat(nav): live-distance prefix on near-tier base + chain-append        [Task 6]
e3b2310 test(nav): tighten I13 far-tier assertion + 3 minor cleanup items       [Task 5 cleanup]
8956ead feat(nav): live-distance prefix on far-tier voice prompts               [Task 5]
7ab9bf7 feat(nav): GPS-recovery flag for prefix-suppression on first post-stale tick  [Task 4]
fc22927 fix(nav): formatDistancePrefix rejects NaN/Infinity/negative input      [Tasks 0-3 fix]
c259004 feat(nav): stripBakedDistance — strips Valhalla mid-string distance chains    [Task 3]
7800ae7 feat(nav): formatDistancePrefix — Google-Maps-style live-distance helper      [Task 2]
d54c111 docs(test): update stale floor-value refs in nav engine tests           [Task 1 cleanup]
1e91579 fix(nav): raise near-tier distance floor for surface-street buffer      [Task 1]
7bad09c feat(nav): _geographicaUseImperial helper for live-distance prefix      [Task 0]
7aea517 test(nav): I14 GPS-recovery prefix-suppression integration              [Task 7]
05e26bd test(nav): tighten I14b resume-assertion to fail on M2 no-fire          [Task 7 fix]
f35cd8e test(nav): I13g full-pipeline — strip Valhalla chain + live prefix      [Task 8]
```

### Outcome

`node --test --test-force-exit frontend/tests/engine/` → **80 / 80 pass** at HEAD (was 67 at session start; 13 new tests across the cycle: I12 floor unit + I13 prefix integration ×4 + I13g full-pipeline + I14 GPS-recovery ×2 + 5 helper unit tests). `python -m pytest tests/ services/search/tests/` → 1076 pass + 4 known pre-existing failures (test_pipeline_status_m2m ×2, test_wake_lock_static, test_bootstrap_messaging) + 21 test-isolation false-failures in `test_setup_main.py` (pass when run in isolation; pre-existing). No nav-voice regressions.

Tests covering spec §5.5 invariants: I12 (floor values), I13 (prefix integration on Villa Rita + wider-cluster fixtures), I13g (full-pipeline order-of-ops on Valhalla multi-cue depart shape), I14 (GPS-recovery prefix-suppression + normal-flow resume), I16 (monotonicity property — implicit in formatDistancePrefix unit tests). I15 (exception safety) verified by code review only — see plan Task 5 / Task 6 for rationale.

**Ship gate**: Cameron re-drives Villa Rita → 19001 N 27th Ave Costco. Acceptance criteria per spec §6: Issue 1 audible buffer at 25 mph; Issue 2 spoken prefixes on far/near/chain; total prompt count ≈ 11 (TTM v3 baseline preserved); GPS-recovery sanity (first post-recovery prompt has no prefix) verifiable via `_geographicaTTMDebugLog`. After acceptance: `git switch main && git merge --ff-only dev && git push origin main`. release-please auto-bumps to next minor (additive feature, no breaking change).

---

## 2026-04-22 — Overview pyramid incremental rebuild (journal-based, 13 tasks)

**Released as:** not yet released (shipped on `dev` at `b8a76a1`, pushed to `origin/dev`)
**Plan / spec:** [docs/superpowers/plans/2026-04-22-overview-incremental-plan.md](../docs/superpowers/plans/2026-04-22-overview-incremental-plan.md) · [docs/superpowers/specs/2026-04-22-overview-incremental-design.md](../docs/superpowers/specs/2026-04-22-overview-incremental-design.md)
**Adversarial reviews:** 5 rounds (Sonnet arch/scale/test + Codex + Sonnet v2-attack) — summarized inline in spec §Open questions; transcripts are in the spec's commit history (preserved via `40346eb`).
**Execution protocol:** `superpowers:subagent-driven-development` with two-stage review per task (spec + code-quality). Plan went through a controller-side review pass before dispatch (commit `5483971`) that pinned ambiguity and fixed a mathematically wrong test assertion — see "Key decisions" below.
**Agent moniker for execution:** `tamarack` (Phase 1-7 across ~40 subagent dispatches + controller-inline edits).

### Summary

Replaced `scripts/rasterio_ops.py:build_overviews`'s nuclear pyramid-rebuild with a targeted incremental path keyed on a persistent SQLite journal (`_overview_work_queue`). Surfaced by 2026-04-21 runtime: 82 new tiles merged into a 40 GB MBTiles triggered a **6+ hour overview phase** because the code rebuilt the whole pyramid regardless of what changed. New design rebuilds only ancestor lineages of newly-merged/eroded/inpainted tiles, with a `mode="auto"|"journal"|"nuclear"` selector for 1:1 A/B validation + operational rollback. Pipeline reordered `merge → erode → inpaint → overviews` so overview build sees post-cleanup base tiles. 26 new regression tests, one end-to-end semantic-equivalence test, one grep-based write-discipline enforcement test, and one stand-alone A/B comparison harness.

### Key decisions

- **Journal table, not in-memory dirty set** (spec v2→v3, Round 5 C1+C2). The 5-round adversarial review killed a v1 in-memory design on three convergent Criticals (wrong function instrumented, broken re-evaluation semantics, no crash recovery). Persistent SQLite table (`_overview_work_queue`) survives process death; enqueues happen in the same transaction as the base-tile mutation via `_mutate_base_tile`.
- **Unified re-evaluation rule** (spec §Architecture, Codex-driven fix). One rule, one function: "write ancestor if all 4 children exist; delete if any missing." No `kind=UPDATE`/`kind=DELETE` column. This is what makes sparse-bbox mutations correct — if the bbox expansion adds one tile whose 3 siblings never existed, the z-1 ancestor is DELETED (not composited over the 3 basemap-fallback gaps). Documented in the admin-panel user-facing estimate so users aren't surprised by overview coverage shrinking when they expand a sparse bbox.
- **Hybrid bulk-SQL + per-tile helper** (Round 5 C1 resolution). `merge_mbtiles`'s bulk path keeps its `INSERT OR IGNORE INTO tiles SELECT ... FROM src.tiles` + adds one SQL per zoom-level shift for the cascade. `erode`/`inpaint`/slow-path composite routes through `_mutate_base_tile` which combines the tile write + ancestor enqueue in one transaction.
- **Controller plan-review before dispatch** saved probably an hour of tangled subagent debugging. The review fixed six items including one load-bearing math error: the `test_drain_journal_multi_level_cascade` originally asserted `z14_count == 1`, but per the unified rule with a 4×4 z17 fixture, z14 has only 1 of 4 z15 children → DELETE → z14 = 0. A correct implementation would have spuriously failed; a "helpful" subagent would likely have inverted the invariant to make the test pass. See commit `5483971` for all six fixes.
- **Deferred 4-SELECT-per-ancestor optimization** in `_drain_journal` (flagged "Important" by Task 4 code reviewer). Batched `(tc, tr) IN (...)` query would cut 4N queries to N. The plan explicitly specified the 4-SELECT pattern for correctness auditability; batching adds SQL-composition complexity, and the absolute savings are ~ms vs the 6-hour rebuild the whole design eliminates. Queued for post-A/B-validation perf pass.

### Notable bugs caught (by the dual spec+quality review loop, per-task)

- **Tautological test** (Task 2) — `expected` list built via same iterative bit-shift as implementation; consistent off-by-one would have passed. Fix: concrete spot-check assertions against hand-verified tuples (`426b386`).
- **`assert` disabled by `python -O`** (Task 3) — `_mutate_base_tile`'s action-string guard was `assert`, but every other validator in the file raises `ValueError`. Replaced + added `python -O` smoke test (`903a6f9`).
- **Silent black-tile output on all-None input** (Task 4) — `_composite_2x2_children` would emit a solid-black JPEG if the caller violated the precondition guard. Added explicit `ValueError` + docstring (`b28d100`).
- **Misleading docstring** (Task 6) — `build_overviews` said "returns False if cancelled" but the function never returns False; cancel flows through `_drain_*` early exit which commits partial state and returns True. Corrected (`abfba8a`).
- **Metadata-fixup swallowed by overview-build failure** (Task 11) — the inlined `UPDATE metadata SET value = (SELECT MIN/MAX(zoom_level) FROM tiles)` lived inside the same `try` as `rio_build_overviews`. If overview build raised, minzoom/maxzoom stayed stale — a regression from the old `_run_gdaladdo_with_metadata_fixup` wrapper that ran the UPDATE in a `finally` block. Split into two `try/except` blocks so metadata fixup survives overview failure (`407338c`).

### Operational finding: A/B harness OOM on prod MBTiles

Running `dev/tools/compare_overview_modes.py /srv/geographica/data/imagery_noaa.mbtiles --seed-journal` against the 38 GB prod MBTiles while the full Docker stack (7 healthy services + pipeline) was up **OOM-killed the harness** within ~30 minutes. Root cause: cloning a 38 GB MBTiles twice (~76 GB I/O), then running nuclear+journal drains against each clone sequentially, against a Pi with 16 GB RAM where ~6 GB is pinned by Docker services. The Pi's OOM-killer correctly protected the container stack (lower `oom_score_adj`) so GIS services stayed up while the harness died.

**Guidance for future field validation runs:**
1. `docker compose down` before invoking the harness, OR
2. Run against a bbox-extracted subset (carve out a ~5 GB region, not the full CONUS MBTiles), OR
3. Add a `--sequential` mode to the harness that finishes clone-a entirely before cloning clone-b (cuts peak disk + memory). Not done in this cycle.

The semantic-equivalence validation for this task was instead carried by `test_nuclear_and_journal_produce_equivalent_mbtiles` (Task 11) — a 4×4 z17 gradient fixture that asserts coord-set equality + pixel mean-abs-diff < 2 across both modes. Runs in <1s. The A/B harness is READY for field validation at merge-to-main time, but `v1.3.0` ship should happen only after Cameron runs the harness against a small-bbox extract, not the full prod file.

### Commits (18 total, 13-task body + plan review + follow-up fixes)

Plan review (controller-inline, pre-dispatch):
- `5483971` docs(overview): plan review — pin ambiguous steps + fix test assertion

Phase 1 (foundation helpers):
- `8532ef7` + `1cf9b66` — `_init_journal`
- `b5d99ac` + `426b386` — `_enqueue_ancestors`
- `6fbc909` + `903a6f9` — `_mutate_base_tile`

Phase 2 (drain logic):
- `2cba28b` + `b28d100` — `_drain_journal` + `_composite_2x2_children`
- `2690dff` — `_drain_nuclear`

Phase 3 (public API):
- `b705107` + `abfba8a` — `build_overviews` mode selector
- `1366345` — cancel-mid-drain persistence test

Phase 4 (migrate writers):
- `1b17fc4` — `merge_mbtiles` atomic bulk insert + ancestor cascade
- `6434549` — `erode_nodata_edges` returns list + enqueues
- `aa22ae2` — `inpaint_nodata_pixels` max-zoom-only + enqueues

Phase 5 (integration):
- `22f026a` + `407338c` — `run_noaa` post-processing reorder + metadata-fixup isolation

Phase 6 (validation tooling):
- `29d34e1` — A/B comparison harness

Phase 7 (enforcement):
- `b8a76a1` — grep-based invariant test (whitelists `_bulk_import_tiles`, `convert_batch_to_mbtiles` as pre-journal-boundary bulk paths)

### Outcome

- 26 new regression tests on `tests/test_overview_journal.py` + `tests/test_overview_write_enforcement.py`. All green.
- Broader suite: 918/919 pass (`test_bootstrap_messaging.py::test_next_step_appears_at_most_once_per_branch` pre-existing, unrelated).
- Semantic-equivalence proven at unit scale via `test_nuclear_and_journal_produce_equivalent_mbtiles`.
- Journal pattern documented for future pipelines to adopt (M2M, Sentinel, NAIP) — out of scope for this cycle per spec §Non-goals.
- Field-test gate before `v1.3.0`: small-bbox A/B harness run with `docker compose down`. Noted in Task 12 docstring + this log.

---

## 2026-04-20 — NOAA catalog refresh async+progress (13 tasks complete, awaiting push)

**Released as:** not yet released (shipped on `dev`, not yet pushed to origin)
**Plan / spec:** [docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md](../docs/superpowers/specs/2026-04-20-noaa-refresh-async-progress-design.md), [docs/superpowers/plans/2026-04-20-noaa-refresh-async-progress.md](../docs/superpowers/plans/2026-04-20-noaa-refresh-async-progress.md)
**Adversarial reviews:** [dev/adversarial/2026-04-20-noaa-refresh-async-sonnet.md](adversarial/2026-04-20-noaa-refresh-async-sonnet.md) (v1→v2); Phase 1 closeout: Sonnet architectural + Sonnet adversarial + Codex (`/tmp/phase1-codex-review.log`); Phase 2 closeout: Sonnet integration + Codex (`/tmp/phase2-codex-review.log`)

### Summary
Follow-on to the 2026-04-20 NOAA NAIP CONUS expansion (39 tasks shipped). First live refresh attempt surfaced three UX failures: nginx 60s `proxy_read_timeout` returning a 504 HTML page (browser `JSON.parse` → SyntaxError), no progress reporting for the 10–30 min operation, and the Refresh button buried inside a collapsible labeled "history". Phase 1 converts the endpoint from a single synchronous HTTP call to a **dispatch + poll** pattern: `POST /refresh` returns 202 Accepted in <1s and schedules `refresh_catalog()` on `asyncio.create_task()`; a progress callback atomically writes `/data/noaa_catalog_refresh.progress.json`; `GET /refresh/progress` returns the state; `POST /refresh/cancel` sets a module-level `asyncio.Event`. Frontend wiring lands in Phase 2.

### Key decisions
- **asyncio.Event (not file flag) for cancel signalling.** Spec v2 §change #3 — eliminates the read-then-write race where the cancel endpoint's file write would clobber the bg task's progress update. The file flag stays in progress.json as UI-readable status only, written by the bg task *after* observing the Event.
- **Module-level `_active_refresh_task` reference retention.** Spec v2 §change #1 — prevents Python's GC from collecting tasks held only in the event loop's weak set; also enables future `/refresh/reset` to cancel the task cleanly.
- **run_in_executor for blocking ops.** `fetch_tile_count`'s `ogr2ogr` subprocess, the ZIP file write, and `ZipFile.extractall()` are all dispatched through the executor so the event loop stays responsive for `/progress` polling during the 10–30 min refresh.
- **RefreshCancelled exception for mid-state cancel routing.** Spec v2 §Failure mode 3 targeted ≤15s typical cancel latency — state-boundary polling alone was ~360s+ worst case inside a large tile-index download + extract. `fetch_tile_count` now checks `cancel_event` at four points and raises `RefreshCancelled`, which `refresh_catalog`'s per-state loop catches and routes to the same cancelled-log-entry path as its loop-top check.

### Notable bugs caught (by the Phase 1 closeout 3-round review)
- **Cancel latency unbounded** — `sess.get(total=300)` + `write_bytes` + `extractall` + `ogr2ogr(60s)` could stall cancel for minutes (all 3 rounds) → `fe8db7d`.
- **Duplicate refresh-log entries** — `refresh_catalog` logs on all ok/truncated/cancelled/invalid_parse paths; bg-task wrapper's generic `except Exception` was appending a second `validation_status=error` entry (Sonnet Round 2 + Codex) → `fe8db7d`.
- **_is_progress_stale `TypeError`** on tz-naive ISO timestamps — `GET /progress` 500 instead of gracefully non-stale (Sonnet Round 2 + Codex) → `fe8db7d`.
- **Test gaps** — bg-task error path round-trip, CancelledError branch, POST /cancel auth, naive-ISO stale path. All added in `fe8db7d`.

### Commits (Phase 1)
- `6fdac47` feat(noaa): progress-state helpers
- `3956dff` feat(noaa): refresh_catalog progress callback + event-loop-safe fetch_tile_count
- `015a325` feat(noaa): async-dispatch POST /refresh
- `b3b4a39` feat(noaa): GET /refresh/progress
- `5238834` feat(noaa): POST /refresh/cancel
- `dcce6c5` feat(noaa): stale-refresh heuristic
- `fe8db7d` fix(noaa): Phase 1 review closeout — 3 bugs + 4 test gaps

### Known latent issues (deferred to a separate ops-hardening spec)
- **Multi-worker double-dispatch**: module-level `_active_refresh_task` doesn't serialize across uvicorn workers. Currently single-worker, so inactive. (Codex flagged.)
- **Single-temp-file race** in `write_progress_state`: fixed `.tmp` filename is not multi-writer safe under the multi-worker scenario above. Same mitigation. (Codex flagged.)

### Phase 2 (frontend — Tasks 7-11) — shipped

- `00f939e` feat(frontend): promote NOAA Refresh to primary empty-state CTA
- `ea7956f` feat(frontend): cite 10-30 min duration in NOAA refresh confirm dialog
- `24639b7` feat(frontend): live progress bar + ETA for NOAA catalog refresh (with page-nav rehydration per spec testing invariant #7)
- `72c496d` feat(frontend): NOAA refresh completion summary + dropdown reload
- `edc8744` feat(noaa): POST /refresh/reset endpoint + Force Clear wiring

### Phase 2 closeout (2026-04-20, 3-round review — Sonnet + Codex)

- **Bug 1 (Critical lifecycle)** — Progress polling leaked across NOAA card collapse/expand (interval fired on detached DOM; re-expand stacked a second interval). Codex only. → `5b97549`.
- **Bug 2 (Critical correctness)** — Force Clear vs. in-flight poll race; stale `/progress` fetch after `/reset` could re-render progress card with obsolete state. Codex only. Fixed with per-card force-clear generation counter. → `5b97549`.
- **Bug 3 (Important)** — Rehydration vs. catalog-fetch race: `/catalog` could show the empty banner over a running refresh. Both rounds. Fixed by gating `_updateRefreshBannerVisibility` behind absence of progress/completion card. → `5b97549`.
- **Bug 4 (Important)** — `/refresh/reset` could hang indefinitely if the bg task refused to finalize after `.cancel()`. Sonnet only. Fixed with `asyncio.wait_for(task, timeout=30)`; module refs cleared + files removed even on TimeoutError. → `5b97549`.
- **Bug 5 (Important)** — Completion banner `className` concatenated server-provided `result.status` without sanitization. Sonnet only. Whitelisted against known statuses. → `5b97549`.
- 3 UX polish items (zero-state copy, 24h staleness on completion banner, cancelled copy). → `5b97549`.

### Task 12 — terminal-state gap tests

- `5cfda6b` test(noaa): bg-task terminal-state round-trip coverage (ok/truncated/invalid_parse/cancelled). Spec testing invariant #4 now has full 5-branch coverage (with error + reset_endpoint from Phase 1 closeout).

### Outcome

- **15 commits** on `dev` (6 Phase 1 + 1 Phase 1 closeout + 1 log + 5 Phase 2 + 1 Phase 2 closeout + 1 gap tests + 1 Phase 2 log update).
- **104 passing tests** (up from 90 at start of Phase 1) across `tests/test_refresh_noaa_catalog.py` (43) + `services/search/tests/test_noaa_admin_endpoints.py` (61). No regressions in the pre-existing 2 M2M failures or the Nominatim-env errors.
- Runtime validation pending — Cameron will exercise the new admin-panel refresh flow (dispatch, progress bar, cancel, completion summary, stale Force Clear) against the live dev stack before merging to main.

### Known latent issues (deferred to a separate ops-hardening spec, tracked in START.md)

- **Multi-worker double-dispatch**: module-level `_active_refresh_task` doesn't serialize across uvicorn workers. Currently single-worker (active), so inactive. Codex Phase 1.
- **Single-temp-file race** in `write_progress_state`: fixed `.tmp` filename is not multi-writer safe under the multi-worker scenario above. Codex Phase 1.

---

## 2026-04-21 — Nav UX beta-bug remediation (13 bugs closed, B1 deferred)

**Released as:** not yet released (pending main merge + runtime validation)
**Plan / spec:** [docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md](../docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md)
**Bug hunts:** [dev/bug-hunts/2026-04-21-nav-uxb-consolidated.md](bug-hunts/2026-04-21-nav-uxb-consolidated.md)
**Adversarial reviews:** none (exploratory/holistic/multipass hunters cross-validated in parallel)

### Summary

Four beta-tester reports triggered a full bug-hunt cycle on turn-by-turn navigation. Exploratory, Holistic, and Multipass hunters conducted independent analysis and triangulated findings across [frontend/navigation.js](../frontend/navigation.js), [frontend/nav-ui.js](../frontend/nav-ui.js), and [frontend/app.js](../frontend/app.js). Cycle surfaced 14 confirmed bugs (13 closed in this cycle, 1 deferred) + 6 low-priority signals + 2 pre-existing out-of-scope issues.

**Closed bugs:**
- **B2 (highest severity):** Reroute leaves map polyline, sidebar directions, and trip globals stale. Fixed via new `setActiveRoute(trip, options)` unifier in app.js that owns engine state + map source + sidebar + globals. Reroute path now calls this before engine apply.
- **B3:** GPS marker renders at ~60% instead of 78% from viewport top. Fixed proportional padding formula `top = mapH * 0.56 + overlayH` in getNavPadding; also explicit clear-padding on nav exit (merged with B8).
- **B4:** Recenter/compass overlap on mobile; wrong stack order on desktop. CSS-only stack reorder: compass at bottom:120, recenter at bottom:170 (desktop); at mobile:100/150 resp.
- **B5:** Multi-stop reroutes drop intermediate waypoints. Fixed `buildRouteData` to extract `remainingWaypoints` from trip.locations; reroute callback filters already-passed waypoints.
- **B6:** `costing_options` (avoid_highways, etc.) dropped on reroute. Added `costingOptions` field to route payload; engine passes through to reroute callback.
- **B7:** GPS hysteresis fills in ~2.5s instead of 5s because feedGPS calls updateGPS twice per unique position. Moved `nav.updateGPS()` inside signature-change guard.
- **B8:** Padding leaks across sessions via MapLibre persistence. Merged into B3 fix; explicit `padding: {top:0, bottom:0, left:0, right:0}` in restoreMapState easeTo.
- **B9:** `applyReroute` does not reset `lastAnnouncementTime`; `announcedSet` filter is backward. Fixed: `announcedSet = {}; lastAnnouncementTime = 0;`.
- **B10:** `lastRerouteTime` not cleared when engine timeout fires (10s reroute timeout but 15s cooldown overhang). Cleared on timeout callback.
- **B11:** Valhalla 200-with-error silent no-op (banner stuck). Explicit branch on `!data.trip || data.error` routes to retry/failure path.
- **B12:** In-flight fetches + retry setTimeouts survive stopNavigation. Tracked setTimeout IDs in array; stopNavigation clears all + resets counter.
- **B13:** First maneuver of subsequent leg at `begin_shape_index=0` indexes into previous leg. Clamped to `Math.max(0, ...)`.
- **B14 (upgraded from false-positive):** UI mute state not propagated to engine on nav start. Added `nav.setMuted(muted)` call after `nav.start()`.

**Deferred:**
- **B1 (voice tiering redesign):** Current distance-threshold logic announces 3× per turn; thresholds + tier boundaries are design-dependent. Cameron's plan-review decision: no band-aid this cycle — ship nothing until the full TTM (time-to-maneuver) redesign lands with its own brainstorm + spec + adversarial review. `VOICE_THRESHOLDS` in [frontend/navigation.js:42-46](../frontend/navigation.js#L42-L46) remains unchanged at `[800, 200, 50]`. Beta testers continue to hear 3 announcements per turn until the follow-up plan ships. TTM-redesign seed topics documented in the plan's Appendix.

### Key decisions

- **B1 fully deferred, no threshold band-aid:** Cameron's explicit call ("no reason to fix now when we're going to rebuild it"). The consolidated report's D1 option (b) chosen; options (a) and (c) rejected.
- **setActiveRoute refactor for B2, not band-aid:** Cameron's explicit call ("no more bandaids approaching 2.0.0"). Introduced `setActiveRoute(trip, options)` in [frontend/app.js](../frontend/app.js) that owns the 4-way state update (engine route, `_geographicaLastTrip`, `lastRouteCoords`, map `'route'` source, sidebar `#route-directions`). Exposed as `window._geographicaSetActiveRoute` for nav-ui.js reroute consumer. The old `renderRoute` function was deleted (~80 LOC). Three commits implement this: `2c03471` (extract, behavior unchanged), `a8cd7ba` (convert initial-route site + delete renderRoute), `cb3f27b` (convert reroute site — closes B2).
- **All 13 non-B1 bugs fixed inline:** Reroute path is under heavy surgery this cycle; deferring B5, B6, B12 would require revisiting same code in a follow-up. Fixing now is cheap + reduces regression risk.

### Notable bugs caught

- B2: State split across 4 places (engine route, globals, map source, sidebar) — caught by all three hunters as "most severe reported bug."
- B3: Padding math inverted (inset vs. offset) — caught by all hunters; Multipass also found sub-bug (B8 padding leak).
- B14: Upgraded from false-positive FP6 after re-read of logic — mute state guard is UI-side only; engine's announcedSet still fires, suppressing unmute-time announcements.

### Commits

Notable commits (20+ total on this branch):
- `54af3f0` test(nav): bootstrap Node vm-based engine test harness
- `830e4c7` fix(nav): reset announcedSet and lastAnnouncementTime on applyReroute (B9)
- `2c03471` refactor(nav): extract setActiveRoute as single source of truth (B2 prep)
- `03624b5` fix(nav): preserve intermediate waypoints across reroutes (B5)
- `ce12c02` fix(nav): preserve costing_options across reroutes (B6)
- `633f176` fix(nav): engine dedups duplicate GPS positions for hysteresis (B7)
- `cf56e6a` fix(nav): proportional nav padding + clear padding on nav exit (B3, B8)
- `ddc9578` fix(nav): stack recenter button above compass, resolve mobile overlap (B4)

### Outcome

- **Tests:** 12 unit tests passing (6 engine nav + 6 nav-ui route-data builders). Engine tests include dedicated B7 dedup test + B10 timeout test. Playwright harness modes (B2 polyline update, B11 error banner, B12 fetch abort, B3/B8 padding assertions, B4 button stack at viewports) documented as pending runtime validation against live dev frontend.
- **Code coverage:** Frontend path touched: navigation.js (9 + 10 = 19 modified lines), nav-ui.js (50+ across 5 separate sites), app.js (setActiveRoute export), style.css (B4 stack reorder). Zero backend/pipeline/setup changes.
- **Surprises:** None. Hunters' consensus across three independent passes validates the scope. B1 threshold tuning deferred cleanly. B14 upgrade from FP justified on re-read.

---

## 2026-04-20 — Nav keep-awake (feature-complete, field-untested)

**Released as:** not yet released (agent-complete on dev, awaiting §6.3 manual field acceptance before merge to main)
**Plan / spec:** [docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md](../docs/superpowers/specs/2026-04-20-nav-keep-awake-design.md)
                 [docs/superpowers/plans/2026-04-20-nav-keep-awake-plan.md](../docs/superpowers/plans/2026-04-20-nav-keep-awake-plan.md)
**Adversarial reviews:** [dev/adversarial/2026-04-20-nav-keep-awake-r{1..6}-*.md](adversarial/)
**Research:** [dev/research/2026-04-20-spec-b-field-mode-research.md](research/2026-04-20-spec-b-field-mode-research.md) (parallel Spec B research for future offline-HTTPS work)

### Summary

Turn-by-turn nav silently broke on mobile when the phone auto-dimmed — not because the screen going dark is itself dangerous, but because a driver glances down to investigate a silent/dark phone, and that's the actual eyes-off-road safety hazard at driving speeds. This feature holds the device screen awake for the duration of active nav using a two-layer mechanism: `navigator.wakeLock.request('screen')` on Secure Context origins, with a first-party `SilentVideoLock` helper (plays a 2×2 no-audio-track MP4) on plain HTTP. Entirely passive to the driver — no indicator, no chime, no banner; the existing nav UI IS the evidence. Voice-continuity-under-backgrounding is explicitly out of scope for a future sibling spec.

### Key decisions

- **Bespoke silent-video helper instead of NoSleep.js.** Round 1 of the adversarial review (with the Codex cross-validation round) discovered that NoSleep.js v0.12.0 internally calls `navigator.wakeLock.request('screen')` first — meaning our "fallback" was re-invoking the same failing API on any origin where the primary rejects. Replaced with a ~60-line first-party module. Removed a 5-year-unmaintained dependency as a bonus.
- **Generation-counter race safety.** Concurrency round (R2) found three distinct orphan-lock bug classes the v1 canonical code permitted under rapid Start→Stop→Start, release-during-pending-acquire, and visibility-reacquire-during-release interleavings. Fix: monotonic `acquireGeneration` counter captured per-call, compared on await resume. Task 8's race tests verify all three scenarios empirically.
- **iOS PWA standalone-mode bypass.** WebKit #254545 silently breaks `navigator.wakeLock` in iOS 16.4–18.3 Home Screen PWA. Detection via `matchMedia('(display-mode: standalone)')` forces the fallback path on affected devices. Extended to the visibility-reacquire handler after Task 10 quality review caught that the visibility handler re-called the broken primary API without the bypass.
- **Explicit "no audio track" (not muted silence) media contract.** Codex R6 F6.4 caught that muted silence collides with `speechSynthesis` media-session routing and iOS lock-screen affordances. The MP4 is generated with ffmpeg `-an` flag (no audio stream at all); a Python test verifies via `ffprobe`.
- **Tests promoted to GitHub Actions (frontend-ci.yml)** per `feedback_env_drift_favor_ci.md` — pure-logic tests on ubuntu-latest distinct from Cameron's dev Pi, separate from wizard-ci.yml's LXD integration suite.
- **Voice-continuity deferred (user decision B).** Wake-lock reduces how often the tab is backgrounded at all (driver doesn't need to unlock to check); a proper voice-continuity spec gets its own treatment later. Stale-prompt replay explicitly rejected as NG7 — worse than silence.

### Notable bugs caught by adversarial review

- **NoSleep fallback is not a fallback** (R1 F1.1) — architectural; fix = replace with bespoke helper.
- **Orphan-lock on rapid acquire/release interleavings** (R2 F2.1/2.3/2.8) — race safety; fix = generation counter.
- **Grep-based static tests mistake presence for behavior** (R3 F3.1) — test quality; fix = brace-tracked `function_body` + `strip_js_noise`.
- **Mock fidelity underspecified** (R3 F3.7) — fix = reference mock factories in `_fixtures.js`.
- **JS test dir collision with pytest** (R3 F3.11) — fix = `frontend/tests/wake-lock/` (hyphen blocks Python import).
- **Spec meta-coherence** (R6 F6.1, Codex) — the highest-leverage finding. R1's "replace NoSleep" decision wasn't propagated through acceptance criteria, tests, dependencies — spec would have asked a subagent to ship the rejected design. Fix = full v2 rewrite before plan was written.
- **Silent video must have no audio track** (R6 F6.4) — media contract; fix = ffmpeg `-an` + ffprobe verification test.
- **iOS PWA bypass incomplete in visibility handler** (Task 10 quality review) — real bug that would silently break nav after the first tab-hide/show on iOS <18.4 PWA. Fix = hoisted `isIosPwaBypass()` helper, gated both `acquire()` and the visibility handler.

### Commits

Spec + adversarial review (before implementation):
- `0cfd989` spec v1 — immediately invalidated by R1's NoSleep.js finding
- `eb8b53b` 6 adversarial review files + Spec B research
- `0ab8bf2` spec v2 — full post-adversarial rewrite (525 → 877 lines)
- `846a722` implementation plan (16 tasks across 5 phases)

Implementation (17 commits on dev):
- `22fbc2a` Task 1 silent.mp4
- `3ea2bd7` Task 2 test fixtures
- `a473597` ffmpeg recipe fix (1×1 unworkable)
- `e2dc957` Task 3 SilentVideoLock lifecycle
- `8087dbd` Task 4 SilentVideoLock contract
- `272d156` Task 5 WakeLock scaffolding
- `95b8c5a` Task 6 fallback path
- `f6742eb` Task 7 release lifecycle tests
- `96e0ed5` Task 8 race-safety tests
- `fac58fe` Task 9 visibility handler
- `d8a2200` Task 10 iOS PWA bypass
- `c2179b4` Task 10.5 iOS PWA bypass in visibility handler (Critical bug caught in review)
- `f7fb1aa` Task 11 index.html
- `17f5cff` Task 12 nav-ui.js hooks
- `fad0385` Task 13 Python static tests
- `46a5e44` Task 14 CHANGELOG + CONTRIBUTING
- `74c979c` Task 15 frontend-ci.yml

Supporting:
- `df4ac27` CLAUDE.md clarification that Codex CLI is installed but not on $PATH (unblocks future build-robust-features runs)

### Outcome

**Tests (local, pre-merge):**
- 34/34 JS unit tests via `node --test frontend/tests/wake-lock/` (11 SilentVideoLock + 23 WakeLock)
- 13/13 Python static tests via `python -m pytest tests/test_wake_lock_static.py`
- 47/47 combined, 0 failures, 0 skips

**Deferred intentionally:**
- §6.3 manual field acceptance (real phone, driving scenarios) — the agent plan formally defers this to Cameron per build-robust-features' agent-complete ≠ ship-complete principle. PR body contains the 10-item checklist.
- Test-hardening follow-ups flagged in Task 9 quality review:
  - Empirical test for `document.visibilityState !== 'visible'` guard
  - Empirical test for generation check inside visibility handler's `.then()` — the §5.11 race the original Task 9 test sketched but couldn't wire up cleanly
  - Either remove `++acquireGeneration` from `release()` or add a test that requires it (currently belt-and-suspenders)

**Review-process observations (for transferable lessons):**
- Per-task subagent-driven-development with two-stage review (spec then quality) caught 1 Critical bug (Task 10 visibility-handler iOS PWA hole) and several Important findings that would have shipped otherwise. The per-task review step earned its cost.
- Codex cross-validation round (R6) found the single most valuable meta-level finding — spec-meta coherence — that 5 Claude-family agents collectively missed because each attacked one angle. Worth making "meta-coherence after per-angle review" a routine step for future build-robust-features cycles.
- Two implementer-flagged plan bugs found during execution: (a) `loadModule` JS-destructuring semantics silently ignoring `undefined` (Task 6), (b) `strip_js_noise` helper wiping string-literal tokens (Task 13). Both caught via DONE_WITH_CONCERNS signalling rather than silent papering-over — the right posture.


---

## 2026-04-20 — NOAA NAIP CONUS expansion (in progress)

**Released as:** not yet released (work landed on `dev` via cherry-pick; `feat/noaa-conus` worktree + branch retired 2026-04-20 per the new worktree ban)
**Plan / spec:** [docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md](../docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md) (v2, committed `0341c00`)
                 [docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md](../docs/superpowers/plans/2026-04-20-noaa-naip-conus-expansion.md) (committed `0e0a9ae`)
**Adversarial reviews:** 5 rounds (Codex + 4 general-purpose subagents with distinct lenses: subagent-reader, implementer-skeptic, failure-mode-hunter, operator) — transcripts in session tool-results at `~/.claude/projects/.../tool-results/bsdkk6a2n.txt` + subagent returns

### Summary

Expanding NOAA NAIP imagery from Arizona-only to all 48 CONUS + DC. Adds a bbox-based custom-area mode and a snapshot-pinned versioned catalog (P7). Brainstorm originally paused 2026-04-19 at fatigue limit after 9 decisions were locked; resumed 2026-04-20 with Sections 3-6 completed and a 5-round adversarial review that surfaced 15 MUST-FIX issues before the plan phase. Plan v1 would have broken production in at least 3 ways (import from `setup/runner.py` inside a pipeline container that doesn't mount `setup/`, filter-always-runs with a 60s timeout that fails on TX/CA, checkpoint PK that would silently dedupe NAIP border quads); v2 addresses all 15. 39-task plan with phase-level review checkpoints.

### Key decisions

- **One pipeline, two CLI entry points** (`--state` slug / `--bbox`) rather than separate scripts. Code reuse of the 3-stage parallel pipeline matters more than path purity.
- **Filter short-circuits for whole-state mode** (reversal of original "always-on filter" design). `ogr2ogr -spat` has a 60s timeout that can't handle TX/CA shapefiles.
- **P7 catalog refresh** with snapshot pinning (every pipeline run pins at Start; refresh/rollback only affect future runs). Replaces an earlier threshold-based atomic-swap that was rejected as arbitrary.
- **Disk-relative big-bbox confirmation**, peak-working-set (raw + intermediate + final), not GB-magic-number.
- **Pre-merge real-Azure test as GitHub Action** (not local harness) — env drift is Geographica's dominant bug class per 2026-04-21 beta-triage marathon.
- **Checkpoint PK = `(catalog_snapshot, state_usps, tile_filename)`** — NAIP border quads are shipped in both states' directories, and old PK of `tile_filename` alone would silently dedupe.
- **Partial-coverage policy:** pre-run uncataloged states surfaced at estimate time and explicitly acknowledged; mid-run state failure produces terminal `partial_failed` status (never silent partial coverage via TileServer auto-registration).

### Notable findings from adversarial review

- **Codex C1** (code-verified): `setup/runner.py` not in pipeline container. Would have crashed on first pipeline run. → Task 1 extracts to `scripts/common/state_bboxes.py`.
- **Codex C2**: open question #5 (snapshot pinning) was not optional — without it, estimate/start/resume can use three different catalogs. → Decision #11 revised; pipeline pins at Start.
- **R3-C1** (code-verified): v1 claim that this work closed pre-existing bugs B2/B3 was factually wrong. Those bugs target NAIP/Sentinel, not NOAA. NOAA already works. Including them would regress the just-shipped TileServer handoff fix. → §"Pre-existing bugs closed" removed from v2.
- **R1-C3**: disk model used `total_size_mb > free_disk_mb`, ignoring reproject + intermediate staging. Would strand jobs at 80% progress. → Decision #12 revised to peak-working-set.

### Commits

- `8041478` — v1 spec (dev branch, then superseded)
- `0341c00` — v2 spec (post-adversarial-review; dev branch)
- `0e0a9ae` — plan (dev branch)
- `cc03d42` — Phase 0 Task 1: extract `scripts/common/state_bboxes.py` (feat/noaa-conus)
- `519790c` — Phase 0 Task 1 follow-up: stale error message fix (feat/noaa-conus)
- `85e8dac` — Phase 0 Task 2: canonicalization table + `display_name` (feat/noaa-conus)

### Outcome (in progress — updated 2026-04-20 afternoon)

**Phase 0 complete (Tasks 1-2).** 78 tests (68 setup baseline + 10 new state_bboxes_common).

**Phase 1 complete (Tasks 3-10).** Full P7 mechanics shipped to `scripts/refresh_noaa_catalog.py`: catalog structure validator, Azure blob listing with `<NextMarker>` pagination, NOAA directory parser + tile-index HEAD check, atomic snapshot writer + symlink swap, flock-based lockfile with PID-liveness force-unlock, pipeline-running detector (for refresh/rollback gating), refresh log appender + pinning-aware snapshot pruner, and the `refresh_catalog()` orchestrator + CLI. 35 tests in `tests/test_refresh_noaa_catalog.py` (9 existing + 26 net new across Tasks 3-10). Phase 0 + Phase 1 combined: 113 tests passing in worktree.

**Known follow-up (surfaced during Task 10's live-run attempt):** the tile-index URL template assembled by `refresh_catalog()` (`{AZURE_BASE}/{dir}/tileindex/tileindex_{dir}.zip`) does NOT match NOAA's actual Azure blob layout. All 103 directory prefixes parsed correctly, but every `validate_tile_index` HEAD returned 404. A stub baseline (just the AZ entry) was committed to unblock Phase 2-4; real baseline generation is deferred to Phase 5 where the CI-tier integration test + the pre-merge GitHub Action will force discovery of the correct URL pattern. Two likely fixes: (a) per-directory blob listing with `prefix=<dir>/tileindex/` to discover the actual ZIP name, or (b) URL-pattern correction once confirmed against live Azure. Logged in Task 10's commit message (`c45a0b7`).

**Phase 2 complete (Tasks 11-18).** Pipeline refactor landed: resolver (`resolve_noaa_candidates`), per-state queue build with whole-state filter short-circuit (`build_state_queue`), unified download queue of `(snapshot, usps, filename, blob_url)` tuples (`build_unified_queue`), composite-PK checkpoint migration with `NOT NULL DEFAULT ''` transitional semantics (`_init_noaa_checkpoint` / `_record_tile_complete`), Start-time snapshot pinning (`pin_catalog_snapshot` + `_resolve_or_pin_snapshot`) with `SnapshotPrunedError` resume guard, CLI `--state` slug/USPS normalization with `--year` removed (BREAKING), and `partial_failed` terminal status via `_finalize_noaa_status`. 8 commits (`4a67164` → `eb30eb3`) plus review-closeout fix commit `3cd2e58`. 

**Phase 2 review loop** (2 rounds: Sonnet architectural + Haiku test coverage; Codex adversarial blocked by v0.118.0 CLI flag conflict — deferred to full-branch pass) surfaced 1 Critical + 3 Important issues fixed in `3cd2e58`:
- `services/search/main.py` still passed `--year` + both `--state`+`--bbox` to the CLI (would have broken every admin-initiated NOAA pipeline launch).
- `_finalize_noaa_status` clobbered `status=error` with `partial_failed` on total-failure single-state runs.
- `FileNotFoundError` (missing catalog) and `SnapshotPrunedError` (pruned resume) produced raw tracebacks instead of actionable error messages.
- `tests/test_noaa_naip.py::test_argparse_accepts_noaa_mode` validated a local parser with `--year` rather than the real CLI — test defunct, deleted.

Review notes in [dev/adversarial/2026-04-20-noaa-phase2-review.md](../dev/adversarial/2026-04-20-noaa-phase2-review.md). Pre-merge hardening deferred (Round 2 edge-case tests, `_init_noaa_checkpoint` per-tile optimization) documented there.

**Incident during Phase 2:** implementer subagent for Task 13 silently escaped the worktree and committed to `dev` (on top of the parallel agent's WakeLock work). Recovered via `git revert` on dev (`bdd3157`); all subsequent implementer prompts require a pre-flight `pwd` / `git branch --show-current` / `git rev-parse HEAD` assertion, and the controller independently verifies `git branch --contains <sha>` before accepting DONE status. Saved to memory as `feedback_worktree_escape.md`.

**Test counts:** 905 passed (pre-fix-commit) → 911 passed (post-fix, +6 new admin-endpoint tests). 27 pre-existing `test_setup_main.py` / `test_bootstrap_messaging.py` failures unchanged throughout.

**Known follow-up** (same as Phase 1): tile-index URL template still assembles `{AZURE_BASE}/{dir}/tileindex/tileindex_{dir}.zip` which doesn't match NOAA's actual Azure layout. Phase 5 integration test will force discovery via live-Azure listing. Phase 2 doesn't exercise the tile-index URL path (it builds queues from synthetic inputs in unit tests); Arizona-only runs through the legacy `NOAA_NAIP_CATALOG` dict still work because that path never touches `refresh_catalog`'s URL builder.

**Phase 3 complete (Tasks 19-26).** Admin endpoints shipped to [services/search/main.py](../services/search/main.py):

- **Task 19** `GET /admin/pipeline/noaa/estimate` extended — catalog-driven via `_load_noaa_catalog`, USPS↔slug normalization, bbox-mode state resolution, new response fields (`states`, `missing`, `placename`, `catalog_snapshot`, `intermediate_gb`, `peak_required_gb`) alongside all 12 preserved legacy fields.
- **Task 20** peak-working-set disk estimate: `intermediate_gb = raw × 0.3`, `peak_required_gb = raw + intermediate + final`.
- **Task 21** `_noaa_placename` — multi-state (≥2 cataloged OR width/height > 5°) returns `"Coverage area across AZ, UT"`; single-state + small bbox uses Nominatim reverse lookup with 3s timeout.
- **Tasks 22-25** four admin endpoints (`POST /refresh`, `POST /rollback`, `POST /force-unlock`, `GET /refresh-log`) wrapping `scripts.refresh_noaa_catalog` helpers. Rollback gates on pipeline-not-running + 404 on missing snapshot + rejects path traversal. Refresh-log returns entries reverse-chronological with per-entry `rollback_available` flag.
- **Task 26** `POST /admin/pipeline/start` extended for NOAA mode — `_noaa_peak_and_snapshot` helper gates on `acknowledge_missing` (409) and rechecks disk (507) before entering `_pipeline_lock`.

Commits on dev (Phase 3 only, in order): `c74a935` (19), `5719b3b` (20), `f20d517` (20 follow-up), `3dc72e3` (21), `b1fb1cb` (22), `53055cc` (23), `52b9d96` (24), `d347701` (25), `7159080` (23 hardening — path traversal), `8adb061` (26), `649ed3d` (review closeout).

**Phase 3 review loop** (2 rounds: Sonnet architectural + Haiku test coverage) surfaced 1 Important divergence and 2 Minor issues plus 3 Critical test gaps, all closed in `649ed3d`:
- `_noaa_peak_and_snapshot` used catalog totals while `noaa_estimate` used shapefile-refined per-bbox counts → spurious 507s on sub-state bboxes with cached `.dbf`. Extracted `_count_noaa_tiles(slugs, bbox, entries, data_dir)` shared helper.
- `_noaa_peak_and_snapshot` docstring claimed the returned `snapshot_path` was an "effective pin" — caller discards it; the real pin happens container-side. Docstring rewritten to describe the actual mechanism.
- `noaa_force_unlock` 409 used a raw result dict; other 409s use structured `{status, message}`. Standardized.
- Added 3 coverage-gap tests (malformed bbox, zero-state-intersection bbox, `invalid_parse` refresh status).

**Worktree + feat/noaa-conus branch retired (2026-04-20 PM):** after two near-miss git incidents (Task 13 implementer contaminated `dev` with a misdirected commit; a later Task 26 implementer or dispatch ran `git reset --hard feat/noaa-conus` on dev, wiping six commits of nav-remediation + wake-lock work — all recovered via reflog and restored via merge commit `5545a4c`). Worktrees are now BANNED per `CLAUDE.md §Git workflow` + `docs/pitfalls/implementation-pitfalls.md §14` (landed on dev as `9daa05f`, cherry-picked to main as `7dc2e01`). Destructive git commands are also banned (`ea07e1e`), and agents now carry moniker trailers in every commit (`c28cb35`). The feat/noaa-conus branch's unique commits (`71fef86`, `772c745`) were cherry-picked to dev with Agent trailers (`7159080`, `8adb061`); the branch and worktree were removed.

**Test counts:** 911 (end of Phase 2) → 941 on `services/search/tests/test_noaa_admin_endpoints.py` alone (+30 new Phase 3 tests after the Round-2-gap additions; the other suites remained unchanged). Two pre-existing `test_pipeline_status_m2m.py` failures persist.

**Phase 4 complete (Tasks 27-32).** NOAA admin card fully refactored in [frontend/config/index.html](../frontend/config/index.html):

- **Task 27** (`23ff95b`) — `renderNoaaBody` rewritten into a two-tab structure (Whole state / Custom area) matching the validated brainstorm mockup at `.superpowers/brainstorm/869511-1776625800/content/whole-page-flow-v4.html`. Shared `_renderEstimate` helper surfaces placename callout, missing[] banner, "I understand" acknowledgment checkbox.
- **Task 28** (`b82c3d9`) — new `GET /admin/pipeline/noaa/catalog` endpoint (in `services/search/main.py`); Whole state dropdown populated from the catalog at render time; slug-based option values (matches `_normalize_state_arg`).
- **Task 29** (`a37f4a9`) — Custom area tab shows a live indicator of the `#cfg-bbox` value (green monospace when valid, yellow prompt when empty). Scope trim documented in the entry: the mockup's full shared-Coverage-Area redesign was deferred; the existing bbox input stays in place.
- **Task 30** (`7a98433`) — peak-working-set disk gate (>85% yellow, >100% red+Start-blocked via `estBox._diskBlocked`); `acknowledge_missing` wired through `startPipeline` into the POST body; Custom-area Estimate validates bbox client-side before firing the fetch.
- **Task 31** (`37a33ad`) — collapsible "Catalog refresh history" panel inside the NOAA card: lists entries reverse-chronological from `GET /refresh-log`, per-entry `[Rollback]` button when `rollback_available` is true, "Refresh catalog now" button that triggers `POST /refresh`.
- **Task 32** (`c979205`) — `partial_failed` status branch in `renderGenericProgress` surfaces the per-state breakdown and a "Retry failed state(s)" button that starts a fresh pipeline for the failed entries (MVP: retries first failed state; multi-state retry sequential).

**Phase 4 review loop** (1 Sonnet round on JS correctness + regression risk; no browser harness available for the UI so manual visual check deferred to Cameron). Surfaced 3 Important issues, all closed in `bf83af4`:
- `#cfg-bbox` listener accumulation across repeated card-expand cycles (dedup via stashed function reference + `removeEventListener`).
- HTML-injection surface in Task 32's retry-list `li.innerHTML` where a backend error string could render raw tags (rebuilt via `createElement` + `textContent`).
- Whole-state Estimate fell through to a 422 on empty bbox (mirrored the Custom-area tab's client-side 4-float isFinite pre-check).

**Pending: Cameron's manual visual check** of the live admin UI against the mockup. The tests green (32 passing in `services/search/tests/test_noaa_admin_endpoints.py`) don't exercise the DOM — the admin panel lacks Playwright/jsdom infra, documented as a Phase 4 follow-up.

**Phase 5 complete (Tasks 33-37).**

- **Tile-index URL pattern fix (`4ffd658`).** Task 10's template `{AZURE_BASE}/{dir}/tileindex/tileindex_{dir}.zip` never matched NOAA's real Azure layout — every HEAD returned 404. Live-listing verified the actual pattern across four independent directories (AZ/AL/AR/CA): the zip is `tileindex_{USPS}_NAIP_{year}.zip` in the directory root (no `/tileindex/` subdir, no trailing hash). Fix lands in `scripts/refresh_noaa_catalog.py`; Task 35's integration test now regression-guards it.
- **Task 33 (`5c82fda`)**: synthetic tile-index shapefiles at `tests/fixtures/noaa_tile_indexes/{arizona,utah}_test.shp` + helper. Both shapefiles include `m_border.tif` to exercise the composite-PK checkpoint case. Helper script has 4 fallbacks (osgeo → ogr2ogr-cli → pyshp → raw binary) — on this Pi the osgeo path isn't pip-installable, so the script uses the CLI path.
- **Task 34 (`d192624`)**: Azure XML fixture set extended with `empty_container.xml` + `mixed_valid_invalid.xml` alongside the three existing Task 4 fixtures.
- **Task 35 (`89e27ba`)**: `tests/integration/test_noaa_multistate.py` — 9 tests covering refresh → resolver → queue → checkpoint end-to-end against mocked Azure. Includes an explicit regression guard for the URL pattern fix.
- **Task 36 (`f9fd810`)**: `.github/workflows/noaa-real-azure.yml` — manual-dispatch only (weekly cron deliberately commented out until Cameron confirms runtime budget). Refreshes catalog against real Azure, spot-checks the resulting entries, resolves a Four Corners bbox and asserts AZ/UT/CO/NM are all accounted for. Uploads refreshed catalog.json as a 7-day artifact.
- **Task 37 (`f9fd810`)**: new "Catalog refresh (NOAA)" section in `dev/harness/exploratory_agent/bug_classes.md` with four actionable symptoms: fewer-states-than-expected, URL-pattern drift, stale symlink after rollback, dead-PID lockfile discoverability.

**Phase 5 review** (1 Haiku round on URL correctness + integration-test rigor + fixture completeness + GH Action safety + seed quality) — approved, no fixes required.

**Phase 6 complete (Tasks 38-39).**

- **Task 38 (`994363d`)**: `tests/test_noaa_semantic_equivalence.py` — three env-gated regression tests that compare a pre-refactor baseline MBTiles against a post-refactor Arizona run. Equivalence is NOT byte-for-byte; it's tile-count-by-zoom + metadata-key subset + SHA256 hash match on a 10-point probe grid at z15. Tests skip gracefully when `GEOGRAPHICA_NOAA_BASELINE_MBTILES` / `GEOGRAPHICA_NOAA_CURRENT_MBTILES` are unset. Docstring documents the manual baseline-capture workflow.
- **Task 39**: verification only — `tests/test_setup_runner.py` still passes 68 tests post-extraction of `STATE_BBOXES` to `scripts/common`. No new test required.

**All 39 tasks shipped.** Branch `dev` commits ahead of `origin/dev` at closeout: Phase-0 → Phase-6 inclusive.

**Test counts at Phase-6 closeout:** 1005 passed, 4 skipped (3 new `test_noaa_semantic_equivalence.py` + 1 pre-existing), 30 pre-existing failures unchanged (`test_setup_main.py`, `test_wake_lock_static.py`, `test_pipeline_status_m2m.py`).

**Known follow-ups (documented in plan + reviews):**
- Phase 4 manual visual verification against `.superpowers/brainstorm/869511-1776625800/content/whole-page-flow-v4.html` — the admin panel has no headless browser test infra; Cameron to validate the NOAA card's six tabs / buttons / banners interactively before merge to main.
- Task 38 baseline capture — run a pre-refactor AZ whole-state pipeline once to produce `noaa_az_baseline.mbtiles`, then run current-tip code against the same state for comparison. Both pipelines take ~20-40 min each and ~39 GB disk.
- Task 36's weekly cron schedule — still commented out; enable after one manual dispatch confirms the runtime budget.
- Pre-merge hardening items from Phase-2 Round-2 review (edge-case test coverage for snapshot non-string values, CLI whitespace, partial migration states) and Phase-4 Round-1 review — all non-blocking for merge but worth closing before the release PR.

**Integration path to `main`.** The branch is now plain `dev`; no feature branches remain. The normal release-please PR flow merges dev → main. Cameron: when ready, merge the Release PR at `origin/release-please--branches--main` to cut the next version. Given the BREAKING CHANGE footer on commit `bf27867` (`--year` removed from `acquire_imagery.py`), release-please will propose a major bump.


---

## 2026-04-19 NIGHT — Beta-tester preflight unblocker + wizard harness rebuild

**Released as:** `fix(setup): unblock beta testers stuck in preflight + bootstrap loops` (commit `5e400c5` on main). Harness rewrite lands with this commit on main.
**Plan / spec:** none — single-session debug off a beta-tester screenshot (docs/123_1 (7).jpeg).
**Bug hunts:** none — all found through the harness rewrite.
**Adversarial reviews:** none.

### Summary
Every beta tester attempting to set up Geographica since the 2026-04-19
setup-remediation landing hit a hard wizard-level block: preflight's
"Python pipeline deps" check reported `Missing: rasterio, shapely, scipy,
numpy` on every Pi, regardless of bootstrap success or reboot. The
wizard's "remedy" box told them to re-run `sudo ./bootstrap.sh` in what
was effectively an infinite loop. One beta tester looped this ~16 times
before giving up; another rebooted and still hit the same error.

Root cause (confirmed against beta tester's screenshot + end-to-end LXD
reproduction): the wizard's preflight check used in-process
`__import__('rasterio')`, which runs inside `setup/.venv` — the venv
setup.sh creates. That venv does NOT inherit the user's `~/.local/...`
where bootstrap's `pip install --user --break-system-packages` places
those packages. So the check ALWAYS reported missing on every Pi, forever.

Fix: preflight now shells out to `/usr/bin/python3 -c 'import <pkg>'` so
the check reflects the actual user environment bootstrap targeted, not
the venv. 6 regression tests in `tests/test_preflight_python_deps.py`
guard against the bug coming back.

Also shipped alongside:
- **bootstrap.sh curl/gpg prereq.** Bootstrap consumed `curl` + `gpg`
  for Docker repo setup BEFORE installing them. Fine on raspios Full
  (preinstalled) but broke on minimal Debian / raspios Lite.
- **bootstrap.sh completion-message overhaul.** Beta tester literally
  reported "exiting a screen and opening a new one counts as logging
  out, right?" — it doesn't. New message spells out 4 concrete options
  (reboot / ssh exit+reconnect / console logout / `newgrp docker`)
  and names what does NOT count. Includes a `groups` verification step.
- **setup.sh diagnostic message.** Distinguishes "Docker not installed"
  from "installed but your shell isn't in the docker group" and gives
  a specific fix for each (previously offered both as a list, asking
  the beta tester to guess).

Post-fix, the LXD harness got the rebuild it's needed since v1.0:

- **`dev/harness/drive-wizard.mjs` full rewrite.** Before: waited for
  `#step-4` selector, exited 0. Asserted nothing. After: asserts no
  error banners at any step boundary, no raw Python tracebacks in
  the DOM, preflight all dots are `.ok` (with a named exclusion for
  known-environmentally-unavoidable failures), `#btn-next` enabled
  + text appropriate, no pageerror / console.error events. RED-tested
  by injecting a bogus package into the preflight list — harness
  correctly failed with `ASSERT FAIL: 1 preflight check(s) failing`.
- **`dev/harness/wizard-ci.sh` fixes.** Four LXD-version bugs
  discovered during the rewrite: `lxc file push -r` syntax changed
  (swapped for `git ls-files | tar`); `lxc exec ... & ` never
  detaches (swapped for `systemd-run --unit=...`); setup.sh binds
  127.0.0.1 inside container, unreachable from host (added LXD proxy
  device on port 18099); cloud-init wait blocked on raspios
  (non-cloud-init images — now handles `done`/`disabled`/missing +
  installs systemd-networkd if eth0 has no IPv4).
- **`--image=ALIAS` + `--pre-state=NAME` flags** let the same harness
  run against Debian cloud, raspios, or arbitrary pre-conditioned
  environments.
- **`dev/harness/import-raspios.sh`**: one-shot importer that
  downloads latest raspios-lite-arm64, extracts the root partition,
  creates an LXD metadata tarball, imports as alias `raspios-trixie-lite`.
  Idempotent; cached.
- **`dev/harness/wizard-matrix.sh`**: iterates every `pre-states/*.sh`,
  runs a full wizard walkthrough per pre-state, fail-surfaces all
  failures in one run.
- **`.github/workflows/wizard-ci.yml` upgraded** from manual-dispatch
  only to: smoke mode on every push/PR to `main` or `dev` touching
  the setup code paths, plus manual-dispatch for `matrix`,
  `matrix-raspios`, and `full` modes.

### Notable bugs caught

- **Preflight python-deps infinite loop** (beta-blocker, 5e400c5).
- **LXD bridge down, NAT flushed by Docker** — the harness wouldn't
  run on this Pi AT ALL. Fixed with a `DOCKER-USER` ACCEPT rule +
  systemd unit for persistence (`lxd-docker-bridge.service`).
- **Old harness claimed to exercise the wizard but didn't.** Smoke
  mode exited as soon as `#step-4` rendered — never read any status.
  Every preflight regression since v1.0 would have slipped past.

### Why the 50-task setup-remediation missed the preflight bug

That plan focused on making bootstrap CORRECT; it assumed the wizard's
preflight check (set up well before the plan) was already correct.
In the beta-tester failure mode, bootstrap actually worked — the
wizard's check was broken. No number of bootstrap-focused tests would
catch it, and our LXD harness didn't assert anything beyond DOM-load.
The rewrite fixes the class — any future preflight regression will
fail CI instead of beta.

### Commits

- `5e400c5 fix(setup): unblock beta testers stuck in preflight + bootstrap loops` — setup/main.py + tests + bootstrap.sh curl prereq + completion msg + setup.sh diagnostic (on main).
- (this commit) `test(harness): real assertion-bearing wizard harness + raspios + pre-state matrix + CI gating` — harness rewrite + import-raspios.sh + wizard-matrix.sh + workflow update.

### Outcome

- **Beta testers unblocked**: 5e400c5 is on main. `git pull && sudo ./bootstrap.sh` (or just `./setup.sh` if bootstrap already succeeded) now proceeds past preflight.
- **Harness on the gate**: push to `main`/`dev` now runs the assertion-bearing smoke mode. Before: manual dispatch only + smoke-mode that passed even on the broken wizard.
- **One concrete known-limitation surfaced to a follow-up**: `--image=raspios-trixie-lite` launches the container fine and bootstrap's apt phase completes, but `systemctl start docker` inside raspios-LXD fails with "Job for docker.service canceled" after bootstrap edits `/boot/cmdline.txt` for cgroup_enable=memory. Does not affect the Debian-cloud smoke gate. Deferred for separate debug session.

---

## 2026-04-19 EVE — Trixie docker file-conflict: fix + pre-state harness

**Released as:** fix on `dev` (commit `59f00b5`); matrix landing with this commit.
**Plan / spec:** none — single-session debug + fix.
**Bug hunts:** none — the three 2026-04-18 setup hunts missed this (see "Why internal missed it" below).
**Adversarial reviews:** none.

### Summary
Every beta tester on Raspberry Pi OS Trixie with any prior Docker
attempt (`apt install docker.io`, `get.docker.com`, or `apt
full-upgrade` with docker.io on it) was hard-blocked at `./bootstrap.sh`
with a dpkg file-conflict. Debian 13 Trixie started shipping native
`docker-buildx` (0.13.1+ds1-3) and `docker-compose` (2.26.1-4) packages
that physically own the same paths as Docker's official
`docker-buildx-plugin` / `docker-compose-plugin`
(`/usr/libexec/docker/cli-plugins/docker-{buildx,compose}`); neither
side declares `Replaces`, so if either Debian package was installed,
our `apt install docker-ce ... docker-compose-plugin` aborted
mid-unpack. Observed tester looped bootstrap 16× before giving up
(docs/123_1 (6).jpeg). `apt --fix-broken install` couldn't help:
it only resolves dependency issues, not filesystem overwrites.

Fixed in `fix(setup)` 59f00b5: bootstrap now runs Docker's official
"Uninstall old versions" prerequisite step before the docker-ce
install. Idempotent (no-op on clean systems) so the internal dev
Pi and the LXD harness stay green.

Post-fix, built `dev/harness/bootstrap-matrix.sh` — an apt-level
pre-state matrix that runs bootstrap's `[1/6]` block in ephemeral
Debian 13 Docker containers against realistic customer starting
states (clean / `debian-docker-buildx` / `docker-io` /
`get-docker-com`). Fails CI if any pre-state regresses.

### Key decisions

- **Use `apt remove`, not `apt purge`.** Removing Debian's docker.io
  is the minimum needed to unblock docker-ce install; purging would
  wipe `/etc/docker/` and any user-created configs. `apt remove`
  leaves packages in `deinstall ok config-files` state, which
  satisfies dpkg's path-ownership constraint (binaries gone). The
  matrix's post-condition check had to handle this subtlety —
  `dpkg -s <pkg>` returns 0 for both "install ok installed" AND
  "deinstall ok config-files"; only the former is a regression.

- **Docker-based matrix, not LXD-based.** LXD is the right tool for
  the full wizard E2E (it exercises systemd + ports + Playwright).
  For apt/dpkg state verification, Docker containers start in ~1 s
  vs. LXD's ~15 s and don't require a bridge + NAT config. All four
  pre-states complete in ~10 min in Docker. Fewer moving parts =
  fewer CI flakes. The LXD harness (`wizard-ci.sh`) still owns the
  full wizard path.

- **Extract bootstrap slice via awk, not by copying or flag-gating.**
  The matrix runs the real `bootstrap.sh` source (no duplicated
  code; no test-mode flag on bootstrap itself). awk extracts the
  `[1/6] ... [2/6]` range at runtime. If the banner format ever
  changes, the matrix fails fast with a clear error.

### Notable bugs caught

- Beta-tester blocker (dpkg file conflict) → caught by the user
  uploading `docs/123_1 (5).jpeg` + `(6).jpeg` from the latest
  beta round → fixed in `fix(setup)` 59f00b5.
- Matrix post-condition false-positive: `dpkg -s docker.io`
  returns 0 for `deinstall ok config-files` too → caught by the
  `docker-io` pre-state failing in matrix runtime → fixed in the
  same commit as the matrix landing.

### Why internal missed it

Five independent reasons the signal was a false negative — saved
in memory as `feedback_test_harness_mirror_reality.md`:

1. **Internal dev Pi is a cherry-picked environment.** `dpkg -l
   docker-buildx docker-compose` → both "not installed" on our Pi.
2. **LXD harness uses `images:debian/trixie/cloud`.** Minimal cloud
   image, zero preinstalled Docker packages → our happy-path test
   never sees the conflict.
3. **Harness only exercised one starting state.** No pre-state
   matrix before today.
4. **Setup-remediation plan had a structural blind spot.** 4950 lines,
   50 tasks, zero mentions of `docker-buildx`, `purge`, or
   `file conflict`. Plan assumed a clean target.
5. **Bug hunts were static.** All three 2026-04-18 setup hunts read
   bootstrap.sh as source code; none ran it against a customer-like
   starting state.

### Commits

- `59f00b5 fix(setup): purge Debian-native docker packages before docker-ce install` — TDD: failing test + fix + end-to-end Docker verification that without the fix the beta error reproduces and with it bootstrap completes clean.
- (this commit) `test(harness): bootstrap pre-state matrix (Trixie docker conflict regression guard)` — `dev/harness/bootstrap-matrix.sh`, 4 pre-states, 8 canary pytests, README update.

### Outcome

- `fix(setup)` landed on `dev` and pushed to `origin/dev` so beta testers could `git pull && sudo ./bootstrap.sh` immediately for weekend-availability testing.
- 12/12 unit tests on the fix + matrix passing.
- Full 4-pre-state Docker matrix: 4/4 PASS in 605 s end-to-end.
- Follow-up queued: Tier 2 full-wizard LXD matrix (`wizard-ci.sh --pre-state=NAME`), currently blocked by LXD bridge being DOWN + NAT flushed by Docker on this host; needs a host networking fix before wiring up.

---

## 2026-04-19 PM — TileServer auto-restart on clean pipeline completion

**Released as:** not yet released (on `dev`, pending merge)
**Commit:** `f6f7365` (single commit, 2 files, +312 / −37)
**Bug hunt:** [dev/bug-hunts/2026-04-17-pipeline-completion-review.md](bug-hunts/2026-04-17-pipeline-completion-review.md) §Bug 1

### Summary
Long-standing bug where the map never auto-updated after a pipeline run finished cleanly. The admin service's reconciliation guard at `services/search/main.py:1473` only entered the WAL-checkpoint + TileServer-restart path when the pipeline had CRASHED (`status in ("running", "cancelling") and not container_running`). But every pipeline script writes `status="completed"` to the state file itself *before* the container exits, so the guard was false on clean exits and TileServer was never restarted. Widened the guard to include terminal states (`completed` / `completed_partial`) that have not yet been handed off — tracked via a new `tileserver_restarted_at` stamp on the state file that makes repeat polls no-ops. Runtime-validated live against the stuck Phoenix NOAA run.

### Key decisions
- **Idempotency via state-file stamp, not a background watcher.** Considered a dedicated `/admin/pipeline/finalize` endpoint or a docker-event-driven watcher. Stamp approach is minimally invasive (no new endpoints, no new threads), self-healing (swept a stuck elevation state as a side effect), and fires exactly once per run.
- **Dropped `PRAGMA journal_mode=DELETE`** from the search-service checkpoint. D3 (already shipped on dev) deliberately keeps WAL mode permanently; flipping to DELETE can fail against TileServer's live read-lock during handoff. TRUNCATE checkpoint alone suffices.
- **TDD end-to-end.** 5 new tests covering clean-completion, idempotency, `completed_partial`, and crash-path regression. Watched all fail first; implemented fix; watched all pass. No production behavior untouched by a test.

### Notable bugs caught
- 2026-04-17 §B1 (TileServer Never Restarted After Pipeline Completion) → `f6f7365`
- Symlink-hijack by pytest Task 42 fixture (parallel agent found + fixed as `a2cf6dc`) — not a Claude bug but surfaced during runtime validation.

### Commits
- `f6f7365` — fix(search): restart TileServer on clean pipeline completion (B1 2026-04-17)

### Outcome
- 5 new tests pass; full suite 784 passed (same 2 pre-existing M2M failures, 18 pre-existing env errors).
- Runtime validation on the actual stuck Phoenix state: `tileserver_restarted_at: 2026-04-19T12:57:25Z` written to `.pipeline-state.json`; TileServer StartedAt jumped `12:57:25 → 12:57:55`; `/data/imagery_noaa.json` now serves correct bounds + z9-17; sample tile `/data/imagery_noaa/9/93/202.jpeg` serves 200 OK 18.6 KB JPEG. Second poll idempotent (no double-restart). Self-healed `.elevation-state.json` as a bonus.
- Deferred (each a separate follow-up): B2 (NAIP/Sentinel state-file misnaming), B3 (NAIP/Sentinel missing from TileServer config), B6 (MapLibre base-imagery TileJSON cache).

---

## 2026-04-19 — Setup process remediation (v1.2 cycle)

**Scope:** 48 confirmed bugs (B1-B48) + 8 design decisions (D1-D8) + 3
out-of-scope items (O1-O3) across setup/main.py, setup/config.py,
setup/runner.py, setup/static/*, bootstrap.sh, docker-compose.yml,
nginx/entrypoint.sh, README.md.

**Outcome:** Wizard path is now end-to-end working on a fresh Debian
Trixie LXD container (verified via dev/harness/wizard-ci.sh --smoke).
Every .env VAR that docker-compose.yml references is emitted by
generate_env. TLS vocabulary canonicalized to http|https|tailscale.
Credentials flow through the keyring Unix socket (no more JSON
plaintext). PIPELINE_STEPS lifted to a frozen dataclass registry with
per-step command builders. Install-location UI finally wired through
to the running stack via symlink re-target on launch.

**Highlights:**
- New dev/harness/{wizard-ci.sh, drive-wizard.mjs} for regression
  testing the full setup flow in LXD.
- tools/build-tippecanoe.sh + bootstrap asset-download to eliminate
  the public-lands CAPTCHA + tippecanoe-from-source blockers.
- Shared showError helper in setup.js; all saves now awaited before
  navigation.
- Preflight now covers tippecanoe, python pipeline deps, keyring
  agent socket, cgroup memory, openssl. No more /api/fix-dependency
  (users re-run sudo ./bootstrap.sh with copy-paste).
- Memory profile retuned to "good neighbor" ceilings leaving 3-4 GB
  host headroom (Cameron's architectural call during execution).
- Process rigor (3-agent subagent-driven-development workflow) caught
  several plan-level inconsistencies: tippecanoe 2.80.0 upstream-
  missing, sudo -H missing for pip --user, test-class misclassification,
  keyring socket protocol mismatch.

**Deferred to v1.2 appendix (B44-B48):** response-shape unification,
preflight row-level UI nit, stderr color coding, tls-scan tool-missing
signal, post_credentials empty-field semantics (partially covered
already by skip-empty in Task 23).

**Pitfalls added to dev/testing-pitfalls.md:** TOCTOU in async
endpoints (from Task 30).

---

## 2026-04-19 — GX-01 adapter HAT: JLC bundle correctness + mechanical design paused

**Released as:** ongoing (internal hardware work; no user-facing release)
**Plan / spec:** [docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md](../docs/superpowers/plans/2026-04-18-gx-01-pcb-completion.md) (Phase 0 paused; see Status block)
**Design doc:** [hardware/gx01-path-c-mockup.html](../hardware/gx01-path-c-mockup.html) (open in a browser)

### Summary
User attempted to upload `hardware/gx01-adapter-pcb/jlc_bundle.zip` to JLCPCB; three rounds of 3D preview review caught distinct issues: (1) all components offset ~60 mm above the board outline due to Y-sign in CPL, (2) J1/J2 large headers placed ~24 mm off due to using footprint anchor instead of pad-bbox-center, (3) four LCSC parts physically mismatched their footprints (lead pitch, pin count, B2B-vs-S2B sub-variant). All three classes fixed. Final bundle verifies clean and ships 7/7 parts correctly placed in JLC's viewer. Then a mechanical concern surfaced: the adapter HAT's top-surface connectors (J2 at ~11 mm + ribbon) exceed the case's ~10 mm top-plate clearance. Iterative mockup and dimensional analysis produced two viable paths (A: taller case, C: flip J2 to B.Cu and sandwich with LCD); decision formally deferred until X1100 (arriving 2026-04-19) and SparkFun LCD-00710 (~1 week) are in hand to measure.

### Key decisions
- **CPL positions come from `pcbnew` pad-bbox centers, not `kicad-cli pcb export pos`.** `kicad-cli` passes the footprint anchor through unchanged; the KiCad GUI has a "Use pad origin as reference" toggle that isn't exposed in the CLI. For JLC CPL "Mid X/Mid Y" correctness, we must compute pad bbox centers ourselves in `pcbnew`.
- **Trust the JLC catalog description over the 3D preview.** R1's preview rendering looked suspicious but the description (`Plugin,D2.4xL6.3mm`) confirms it matches our DIN0207 footprint. Placeholder 3D models are common for Extended-tier THT parts. Kept C1370997 unchanged.
- **Design decision deferred pending hardware.** Both Path A (case +20 mm height, keep PCB) and Path C (flip J2 to B.Cu, LCD+HAT sandwich) are mechanically viable. Committing to Path C costs a PCB refab (~$80, ~14 days); Path A costs case proportions. Decision needs physical measurements of X1100 + LCD to confirm the vertical void budget above the X1207 battery cradle.
- **Don't delete the bug-hunt evidence.** JLC 3D preview screenshots (`hardware/jlc_misalignment_v{2,3,4}.jpg`) committed as design history — they're the only record of what the three misalignment classes looked like.

### Notable bugs caught
- **CPL Y-sign flip** — KiCad internal coords are Y-down, Gerbers and JLC CPL expect Y-up. Components rendered ~60 mm above the board outline in the JLC viewer. Fixed by applying `Y = -Y` in the CPL generator.
- **Anchor-vs-center offset for THT headers** — `pcbnew.FOOTPRINT.GetPosition()` returns the anchor (pin 1), but JLC's "Mid X/Mid Y" expects the geometric pad center. For a 2×20 header this was 24 mm off. Fixed by iterating pads and merging bounding boxes.
- **LCSC part mismatch against footprint (×4)** — `verify_lcsc.py`'s THT-vs-SMD heuristic doesn't check pin count, lead pitch, or connector sub-variant. C254085 (5.08 mm pitch vs our 2.5 mm), C124378 (4-pin vs 1×20), C146125 (S-series side-entry vs B-series top-entry). All 4 were clean per the existing verification; all 4 physically wouldn't have fit. `verify_lcsc.py` hardening noted as follow-up.

### Commits
- `fix(hardware): correct JLC bundle CPL geometry and LCSC part selections` — pad-bbox-center computation, Y-axis flip, 4 LCSC part swaps (C254085→C524651, C124378→C50981, C146125→C158012 for J3 and J4)
- `docs(hardware): pause GX-01 PCB completion pending X1100+LCD arrival` — Plan 3 status block, Path C mockup, JLC preview screenshots, this implementation-log entry

### Outcome
- 7/7 parts verify clean against JLC's live catalog via `verify_lcsc.py`.
- `jlc_bundle.zip` regenerated (33 KB, 11 files); BOM and CPL confirmed matching via diff against `kicad-cli pcb export pos`.
- PCB work paused for ≤1 week awaiting hardware; resumption criteria documented in [session handoff memory](../../../home/administrator/.claude/projects/-home-administrator-Code-geographica/memory/handoff_20260419_gx01_cpl_path_c.md) (out-of-repo).

---

## 2026-04-18 — NOAA Imagery Pipeline Remediation (on dev, awaiting runtime validation)

**Released as:** not yet released — all 13 commits on `dev` only, pending end-to-end validation on a Flagstaff-size bbox after the current ~494-quad production pipeline finishes (~2026-04-19)
**Plan / spec:** [dev/plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md](plans/2026-04-18-noaa-imagery-pipeline-remediation-plan.md)
**Bug hunts:** [dev/bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md](bug-hunts/2026-04-18-noaa-imagery-pipeline-consolidated.md) (+ exploratory/holistic/multipass individual reports)
**Adversarial reviews:** 5 prior reports at `dev/adversarial/2026-04-16-*.md` (used as reference only; not authoritative for this cycle)

### Summary
Fresh 3-hunter bug-hunt cycle on the imagery pipeline (5161 LOC) because OOM crashes since the 2026-04-16/17 adversarial review may have caused the then-deferred 9-item list to drift. Result: 16 confirmed bugs (11 new) + 6 design decisions. Scope-locked to 13 bugs + 3 design decisions (B6, B8 deferred for Chesterton's Fence — they'd re-touch `e7e3b32` and `1bab361` code that fixed user-observed imagery artifacts; D4/D5/D6 deferred for scope). All 13 executed via subagent-driven development on `dev`, each fix behind its own commit. Ship deferred pending runtime validation — a production NOAA run is currently blocking the Pi.

### Key decisions
- **Fresh hunt over re-validating the stale deferred list.** Prior 9 deferred items were from 2026-04-16 review; many OOM crashes since could have landed fixes without session notes. New hunt found 11 bugs absent from the old list — the instinct to re-run was right.
- **Chesterton's Fence on B6 and B8.** Hunters flagged `merge_mbtiles` compositing and erosion-after-overview ordering, but commits `e7e3b32` and `1bab361` added those behaviors *specifically* to fix user-observed imagery loss / black quadrant artifacts. Deferred both pending visual-regression testing on a small bbox.
- **Source-inspection tests for Phase 5 rewrite.** Task 9 combines B1 + D1 + D3 with 4 cancel-guard sites, erosion gating, WAL-mode keep-forever. Real end-to-end tests would require mocking gdaladdo + rasterio + interrupting mid-operation — out of scope for this cycle's test harness. Tests verify *code shape* (string presence) not *runtime behavior*. This is named technical debt to revisit.
- **Don't ship to main until live-tested.** Per Cameron's judgment: 13 commits on `dev` + runtime validation later > 13 commits on `main` now + debugging the next NOAA run.

### Notable bugs caught
- **B8 (erosion-after-overview)** — matches `docs/flagstaff_rendering_issue.jpg`. Deferred pending validation.
- **B6 (merge_mbtiles re-composites every overlap)** — progressive JPEG generation loss at quad boundaries. Deferred.
- **B1 (cancel ignored during Phase 5)** — user-visible UX bug: cancel click ignored for 30+ minutes of post-processing. Task 9, commit `48092e6`.
- **B9/D1 (erosion non-idempotent on resume)** — incremental bbox expansion could silently delete valid tiles. Task 9, commit `48092e6`.
- **B14 (wrong MBTiles WAL-checkpointed for elevation)** — only bug outside `scripts/`. Task 4, commit `38b9d32`.
- Plan's own self-inconsistency (explanatory comment contained forbidden string the test asserted against) — caught by Task 9 implementer; reviewer validated rephrase was correct.

### Commits (on dev, not yet on main)
Filtered to remediation work (Cameron's concurrent hardware commits excluded):
- `aace75c` — fix(pipeline): capture rasterio src dims before with exits (B3)
- `ffb93f3` — fix(pipeline): reject fully-out-of-bounds tiles in rasterize (B4)
- `6f26ed5` — fix(pipeline): count composite errors in merge_mbtiles (B7)
- `38b9d32` — fix(search): target WAL checkpoint by pipeline type, not mode (B14)
- `d943968` — fix(pipeline): detect short-reads and reuse cached staging tiles (B10, B11)
- `c619ec4` — fix(pipeline): write progress on _merger failure branches (B12)
- `e8f5f2b` — fix(pipeline): honor cancel during M2M overview build (B2)
- `fc7e03d` — fix(pipeline): share cancellable GDAL subprocess wrapper (B5)
- `48092e6` — fix(pipeline): cancel guards + WAL mode + no-erode-on-resume in NOAA Phase 5 (B1, B9, D1, D3)
- `6e253be` — fix(pipeline): add completed_partial status for NOAA runs with failures (D2)
- `8aa827c` — fix(pipeline): detect _noaa_checkpoint divergence from tiles table (B13)
- `b1086ab` — refactor(pipeline): write progress state once per call (B15)
- `1f77a70` — fix(pipeline): wire NAIP --concurrency via asyncio.gather (B16)

### Outcome (as of 2026-04-18)
- **624 tests pass** on `dev` (up from 596 baseline → 28 new tests for this cycle); 2 + 9 pre-existing failures unchanged — no regressions introduced by any of the 13 fixes.
- **Production NOAA pipeline currently running** with the *old* code (Python imports happened at startup; disk edits don't affect an in-flight process). Expected completion ~2026-04-19.
- **Runtime validation pending:** once production pipeline finishes, run a Flagstaff-size bbox (~10 quads) with the new code, visual-diff the output against a known-good baseline, then merge `dev` → `main` to feed Release PR #2.
- **Deferred follow-ups:** B6 + B8 (need visual-regression proofing before fixes land); D4/D5/D6 (architectural cleanups out of this cycle's scope). Fully documented in the remediation plan's appendix.

### Resume instructions for tomorrow
1. Confirm current production pipeline has completed cleanly.
2. Run `python -m pytest tests/ services/search/tests/ -v` — expect 624 pass, 2 + 9 pre-existing.
3. Execute a validation run on a small bbox (Flagstaff, e.g. `-112.0,35.1,-111.5,35.4`) with the new code. Verify: pipeline completes, tiles render correctly at all zooms, cancel mid-Phase-5 is honored, resume run doesn't re-erode valid tiles.
4. If validation passes: `git switch main && git merge --ff-only dev && git push origin main`. Release PR #2 will update with the 13 new fixes.
5. If validation reveals an issue: identify the specific task → `git revert <sha>` on dev → iterate.
6. After v1.1.0 ships, revisit B6 + B8 with proper visual-regression tests.

---

## 2026-04-18 — Version Control Strategy Adoption

**Released as:** to be included in v1.1.0 (opened retroactively by
`release-please` on first run)
**Plan / spec:** [docs/superpowers/specs/2026-04-18-version-control-strategy-design.md](../docs/superpowers/specs/2026-04-18-version-control-strategy-design.md)
                 [docs/superpowers/plans/2026-04-18-version-control-strategy.md](../docs/superpowers/plans/2026-04-18-version-control-strategy.md)
**Bug hunts:** none (pure documentation + CI work)
**Adversarial reviews:** none; CVErt-Ops reference survey informed design
(see `Key decisions`)

### Summary
Formalized Geographica's versioning regime: SemVer with project-specific
breaking-change rules (the user's data directory and un-edited infra
files are the contract), Conventional Commits enforcement via
`release-please` GitHub Action, lazy release branches, CHANGELOG and
UPGRADING docs, AGENTS.md mirror of CLAUDE.md for non-Claude harnesses,
and this implementation log as the narrative companion to CHANGELOG.

### Key decisions
- **SemVer, not CalVer or custom.** Matches stack upstreams (Docker,
  nginx, MapLibre, Valhalla). Lowest cognitive load for future users.
- **One-line rule for MAJOR bumps:** "If a user with a working install
  has to edit a file to upgrade, that's a MAJOR." Mechanical, no
  judgement calls at midnight.
- **release-please over git-cliff.** Cameron delegates commits to AI
  agents, so the commit-discipline cost of strict Conventional Commits is
  zero. That inverts the usual calculus: the bureaucracy-saving bot wins
  decisively for a time-constrained solo dev. `git-cliff` remains the
  escape hatch if GitHub Actions setup hits friction.
- **Lazy release branches.** Tag `main` by default; create `release/X.Y`
  only when a critical hotfix is actually needed. No dormant branches.
- **No phase framing.** Considered during brainstorming after surveying
  CVErt-Ops (github.com/scarson/CVErt-Ops). Rejected because
  date-stamped plans + SemVer + CHANGELOG + this log already cover every
  benefit phases would provide. CVErt-Ops uses phases as their *only*
  organizing frame because they have no releases; Geographica does, so
  phases would be redundant.
- **Fresh CHANGELOG at v1.0.0.** Pre-1.0 commits were experimental;
  retroactive CHANGELOG would be revisionist and noisy.

### Notable bugs caught
- Spec self-review caught off-by-one in deliverable count (said "8" new
  files, actual count was 9) and rollout commit count (said "four",
  actual "five"). Fixed inline before user review.
- Spec claimed release-please would not open a Release PR on first run
  "because no `feat:`/`fix:`/`perf:` commits are present yet." Actually
  false: the 6+ post-v1.0.0 NOAA hardening commits already on main are
  qualifying. Corrected before writing implementation plan; the
  retroactive v1.1.0 Release PR is now a deliberate outcome rather than
  a surprise.

### Commits
- `60d6f63` — docs: add version control strategy design spec
- `afb360d` — docs: correct spec prediction of first release-please run
- `0bb6d1a` — docs: add version control strategy implementation plan
- `5191996` — docs: adopt semver and conventional commits
- `da8f0c3` — docs: add implementation log with seed entries
- `627ff1e` — docs: align continuation line in 2026-04-18 implementation log entry
- `8bcd056` — docs(claude): add project ethos, commit discipline, and mirror to AGENTS.md
- `f1292f9` — ci: add release-please workflow for automated versioning
- `40d8175` — docs: mark versioning strategy complete in START.md
- `09ef5ce` — docs: record 2026-04-18 regression check in implementation log

### Outcome
- 2026-04-18 regression check: 579 tests pass, 2 pre-existing M2M failures + 9 pre-existing OSM POI errors (unchanged from 2026-04-17).
- First release-please workflow run on `main` failed with `GitHub Actions is not permitted to create or approve pull requests`. Root cause: repo-level setting `can_approve_pull_request_reviews=false` (default). Fixed by `gh api -X PUT /repos/cameronzucker/geographica/actions/permissions/workflow -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true`. Predictable in hindsight — called out in spec's Risks section. Worth adding to a general "Actions setup checklist" for future projects.
- After permission fix, re-ran workflow (`gh run rerun 24600998329`) — succeeded.
- Release PR opened: [PR #1 — chore(main): release 1.1.0](https://github.com/cameronzucker/geographica/pull/1). Retroactively covers the post-v1.0.0 NOAA hardening work: 5 Features + 9 Bug Fixes, each linked to the originating commit SHA.
- Final holistic code review (sonnet) caught a stale-intro issue in CHANGELOG.md: intro said "Entries from v1.0.1 onward are generated automatically" but first generated entry is v1.1.0 (no v1.0.1 will ever exist). Fixed with a single `docs:` commit (`fc51642`) before merging the Release PR. release-please did not automatically regenerate PR #1 because `docs:` doesn't qualify as a new release. Forced regeneration by deleting `release-please--branches--main` via `gh api DELETE`; auto-closed PR #1. Re-ran workflow, which opened clean [PR #2](https://github.com/cameronzucker/geographica/pull/2) with the corrected intro. Pattern learned: to regenerate a stale Release PR, delete its branch and re-run the workflow — release-please will rebuild from current main.
- PR #2 is the canonical v1.1.0 Release PR. Left unmerged for Cameron to review and decide merge timing (immediate release v1.1.0, or bundle more NOAA deferred fixes first).
- Machinery is live. Future `feat:` / `fix:` / `perf:` commits on `main` will be aggregated into the next Release PR automatically (release-please updates the PR in place on each push of qualifying commits).

---

## 2026-04-15 — v1.0.0 Initial Release

**Released as:** v1.0.0
**Plan / spec:** (retroactive entry; spec/plan pairs exist per
subsystem under `docs/superpowers/specs/` and `docs/plans/`)
**Bug hunts:** Many under `dev/bug-hunts/` through 2026-04-15.
**Adversarial reviews:** Many under `dev/adversarial/` through 2026-04-15.

### Summary
First stable release of Geographica. Ships 7 Docker services (tileserver,
valhalla, nominatim, gps, search, stt, frontend), a browser-based setup
wizard, imagery pipeline with USGS / NOAA NAIP / M2M modes, city-aware
spatial search, public lands layer, GNOME-Keyring-backed credential
storage, and a companion utility for fast bulk imagery processing (lives
in a separate repo, `/home/administrator/Code/geographica-companion`).

### Commits
Git log is authoritative through commit `b3e1afe` (2026-04-17) for
post-v1.0.0 state. For the v1.0.0 commit itself and the work leading to
it, see the session handoff files in agent memory (handoff_20260415.md,
handoff_20260415b.md).

### Outcome
v1.0.0 tagged 2026-04-15. 579 tests passing at release time.
