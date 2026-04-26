# Ruler spec v2 — adversarial review R5: Codex cross-validation
**Reviewer:** Codex (gpt-5.4)
**Date:** 2026-04-24
**Lens:** Cross-validation; integration risks; what R1-R4 missed

## Summary
v2 fixes most of the Sonnet-round ship blockers, especially the Terrarium decode, z=12 rationale, touch-target sizing, and the move away from stale `useImperial` capture. It still is not plan-ready: there is one remaining integration bug that will double-fire reverse geocode when selecting ruler vertices in `editing`, and several spec claims are still underspecified or too optimistic about rerender triggers, style-hook accounting, font fallback, edge-case guards, and test rigor.

The biggest pattern here is that v2 corrected the obvious broken formulas and missing handlers, but it still under-specifies the glue code. This is the final review round; the remaining defects are not cosmetic. They are the kinds of integration seams that ship as “mostly works” and then burn time in QA.

## Findings (CRITICAL / MAJOR / MINOR)

### CRITICAL

#### C1. Editing-state vertex clicks still leak into the generic reverse-geocode handler
Spec §B says `editing` vertex taps select the vertex while only empty-map taps should fall through to reverse geocode (spec lines 140, 150). But `_ruler.isActive()` is intentionally `false` in `editing`, so the proposed bail at the generic click handler is inactive precisely when vertex-selection clicks happen.

The real handler in `frontend/app.js:1622-1635` suppresses reverse geocode only when the click hits these layers:
- `imported-points`
- `imported-lines`
- `imported-polygons`
- `imported-polygon-outlines`
- `search-result-circles`

It does not include any future ruler layers. So in `editing`, a click on `ruler-vertex-hit-circles` will do both things:
- fire the ruler layer click/select path
- then fire the generic map click path and open the reverse-geocode popup

This is the missing fourth integration suppression path. It is not another existing external click handler; it is a missing exclusion in the generic handler’s own feature-hit test.

Required spec change:
- Add an explicit edit at the generic click handler so its `queryRenderedFeatures()` exclusion list includes the ruler hit/select layers, at minimum `ruler-vertex-hit-circles`, `ruler-vertex-circles`, and likely `ruler-line` if segment interactions are ever added.
- Or specify a stronger event contract: the ruler layer handler claims the click and the generic handler bails on `e.defaultPrevented` or an equivalent module-owned flag.
- Update the app.js integration inventory accordingly; this is a distinct integration edit, not covered by the three existing bail points.

Why this is ship-blocking: selecting a vertex is core editing behavior. If every select click also pops a reverse-geocode card, the edit model feels broken.

### MAJOR

#### M1. Unit-toggle rerender is still not specified as an actual mechanism
Spec §A correctly switches the source of truth to `window._geographicaUseImperial`, but then says updates propagate “on the next render tick” (spec lines 62-63). There is no such tick in the current app. The actual unit-radio handler in `frontend/app.js:1086-1100` updates the mirror, rebuilds the scale bar, and refreshes camera status; it does not notify ruler UI.

The navigation precedent in `frontend/navigation.js:204-208` is only a live-read helper. It solves stale reads, not DOM rerender.

As written, v2 leaves two incompatible interpretations:
- ruler rerenders only when some unrelated state change happens later
- ruler wires its own DOM listeners to the unit radios

Those are not equivalent, and the spec never chooses one.

Required spec change:
- Specify the rerender trigger explicitly.
- Best option: the existing unit handler dispatches `geographica:units-changed`, and ruler subscribes to rerender panel, banner text, and sparkline aria-labels without mutating data.
- If you want zero extra app.js coupling, say so explicitly and require `ruler.js` to subscribe directly to `input[name="units"]` changes during `init()`.
- Add an integration test that flips the real radio input and asserts that an already-rendered measurement changes units immediately, without extra map interaction.

R1/R4 caught the stale-source bug. v2 fixes the source, but not the rerender contract.

#### M2. The `addPlaceholderSources()` hook is real app.js work, but the insert-count accounting still omits it
Spec §D says style-load reattach must happen by extending `addPlaceholderSources()` so it calls `_ruler.reattachSources(map)` (spec line 209). That means `frontend/app.js` needs another edit inside the centralized source/layer bootstrap function at `frontend/app.js:295+`.

But the integration inventory in §A still claims “five inserts” plus one whitelist edit, and the coordination section repeats “five small inserts + one whitelist edit” (spec lines 88-95, 438-444). That is false. Even before R5’s new `editing`-state click fix, v2 already required another app.js modification for the style-load hook.

This matters because the spec is explicitly using insert counts to reason about merge-risk and implementation scope. If that accounting is wrong in the spec, the work decomposition is wrong too.

Required spec change:
- Count the `addPlaceholderSources()` hook as an app.js edit.
- Update the integration surface summary to reflect the real number of app.js touch points.
- Stop describing the app.js surface as “five inserts + one edit”; after R5 it is at least five inserts plus three edits, and more if you add an explicit unit-change event dispatch.

#### M3. The ruler label font stack is wrong relative to the actual style corpus
Spec §D requires `text-font: ['Metropolis Regular']` for `ruler-vertex-labels` and repeats that rule in the pitfalls checklist (spec lines 202, 430). That is not the prevailing style contract in the shipped tileserver styles.

Actual styles use a two-font fallback for normal labels:
- `tileserver/styles/positron/style.json:662` → `["Metropolis Regular", "Noto Sans Regular"]`
- `tileserver/styles/darkmatter/style.json:743` → `["Metropolis Regular", "Noto Sans Regular"]`
- `tileserver/styles/hybrid/style.local.json:1196-1198` → same two-font fallback

There is one single-font local-style exception for housenumbers in `tileserver/styles/positron/style.local.json:293-295`, but that is clearly not the general pattern for normal map text.

Required spec change:
- Change the ruler symbol layer to `text-font: ['Metropolis Regular', 'Noto Sans Regular']`.
- Update the checklist language to match the actual style-family convention instead of restating the wrong single-font rule.

This is not just aesthetic. The single-font stack is brittle for fallback glyph coverage.

#### M4. Terrarium decode is fixed, but no-data / impossible-value guards are still missing
The decode formula in §E.3 is now correct (spec lines 284-289). The spec still does nothing to prevent impossible pixels from poisoning the profile.

A raw Terrarium decode of `(0,0,0)` yields `-32768m`. If a tile edge, transparent pixel, corrupted read, or unexpected sentinel leaks through, that value will dominate min/max and likely gain/loss too. The spec currently says only “compute min/max/gain/loss on non-null samples” (spec line 312), but it never defines when a decoded sample becomes `null` for being impossible.

Required spec change:
- Define a decode guard.
- Minimum: if alpha is 0, return `null`.
- Also clamp decoded values outside a plausible DEM range, e.g. `< -500` or `> 9000`, to `null`.
- Add explicit tests for `(0,0,0)`, alpha-zero pixels, and out-of-range decoded heights.
- Update the edge-case table to say these become partial coverage, not absurd numeric extremes.

R2 hinted at this. v2 still ships without the guard.

#### M5. The test plan still misses the highest-value behavior-regression cases
The current test list covers geodesy, decode, state transitions, sparkline geometry, and basic keyboard handling (spec lines 366-381). It still misses several regressions that are likely in real implementation:

- LRU eviction is untested. There is no test that proves the cache actually evicts and stays bounded despite the spec mandating an LRU with a 30-tile cap.
- rAF drag coalescing is untested. The spec claims drag updates are coalesced by `requestAnimationFrame`, but there is no test proving repeated `mousemove`/`touchmove` events collapse to one `setData()` per frame.
- Multitouch cancel is untested. The edge-case table says `e.touches.length > 1` cancels drag, but there is no touch-specific test covering it.
- Unit rerender integration is untested. `test_unit_format.js` only validates the pure formatter, not the actual rerender path.
- The new R5 editing-click fix would be untested. The source-grep enforcement test currently only checks three bail regions. If the generic handler also needs ruler-layer exclusions, that enforcement must expand.

Required spec change:
- Add `test_tile_cache_lru.js`
- Add `test_drag_raf.js`
- Add `test_touch_multitouch_cancel.js`
- Add `test_units_rerender_integration.js`
- Expand the app.js enforcement test to verify the generic-click exclusion includes ruler layers or an equivalent claimed-click contract

#### M6. The manual ship-gate checklist still contains vague language that invites self-deceptive passes
The manual checklist is much better than v1, but several items are still too mushy to act as a release gate:
- “Gloved fingers ... vertex tap-target reachable”
- “HTTPS Tailscale + HTTP LAN: ruler works identically”
- “1000-mile path ... UI responsive”
- “Color contrast in sunlight ... clearly visible”
- “VoiceOver ... announced”

Those lines are not falsifiable as written. A tired reviewer can check them off after a casual glance.

Required spec change:
- Replace subjective wording with observable acceptance criteria.
- Example replacements:
- “Gloved fingers”: 8/10 first-attempt taps on a vertex must select without opening a reverse-geocode popup.
- “HTTP LAN vs HTTPS Tailscale”: same path, same units, same click flows, and elevation state transitions match; timing differences acceptable, missing UI states not acceptable.
- “1000-mile path”: banner, panel, and map remain interactive; explicit partial-profile notice appears.
- “VoiceOver”: row announces label + coordinates + selection state; sparkline announces min/max/gain/loss once; banner cancel button is focusable and named.

If this is the final adversarial round, the checklist should behave like a real ship gate, not a vibes list.

#### M7. The “KMZ-serializable” claim is broader than the data shape actually warrants
The spec claims the ruler state is “KMZ-serializable” both in the non-goals framing and the canonical state object heading (spec lines 35, 97). That is too broad.

What the shape actually supports is narrower:
- `vertices` can be exported to a minimal KML `LineString` coordinate list
- vertex labels can become names for point Placemarks if you choose to emit them
- computed metrics like `segments`, `coverageGaps`, `samplingState`, `samplingProgress`, and selection/edit-mode fields are not KML semantics

So yes, the geometry is exportable. No, the state shape is not a general “KMZ-serializable” object in any round-trippable sense.

Required spec change:
- Narrow the claim to: “The core geometry (`vertices`) is exportable to a minimal KML/KMZ LineString plus optional point Placemarks.”
- Do not imply that the whole runtime state object is the future persistence format.

This matters because broad future-proofing claims become architectural traps later.

### MINOR

#### N1. The spec still has no explicit English-only/i18n boundary
All user-facing strings, ARIA labels, unit abbreviations, decimal formatting, and hemisphere letters are English-only and hardcoded. That is consistent with today’s app, but the spec should say so instead of sounding locale-agnostic.

#### N2. Security posture is acceptable today only because ruler labels are internal
Current labels are generated as `V1`, `V2`, etc., so there is no immediate XSS surface. But the spec’s forward reference to persistence/export makes it likely that user-supplied names arrive later. Add one sentence now: ruler DOM rendering uses `textContent`, never `innerHTML`, for labels and stats. That matches the broader frontend posture in `app.js`, where imported HTML is explicitly sanitized with DOMPurify before insertion.

#### N3. Browser back-button behavior is not defined
The app does not currently use `history.pushState`, `replaceState`, `popstate`, or hash routing for sidebar tabs or measure state. That is fine. The spec should explicitly keep it that way for v1 so no one “improves” the feature by polluting browser history with draw/edit state.

#### N4. `test_terrain_rgb.js` keeps the wrong mental model alive
The test filename in §Testing still says `test_terrain_rgb.js` even though the whole point of R1/R2/R4 was that these are Terrarium tiles, not Mapbox Terrain-RGB. Rename it to `test_terrarium_decode.js` or `test_elevation_decode.js`.

## Cross-validation against R1-R4
R1-R4 did catch the major first-order failures, and v2 fixes most of them correctly.

- Terrarium decode: fixed correctly in §E.3. This was the biggest v1 math bug.
- z=12 resolution rationale: corrected correctly; the spec now states the real ~32 m/px figure and ties z=12 to actual data availability.
- `useImperial` source-of-truth: fixed partially. The stale-capture bug is gone because the spec now points at `window._geographicaUseImperial`, but the UI rerender trigger remains unspecified.
- Touch target sizing / touch thresholds / banner collision: substantially fixed. v2 is much more concrete than v1 on hit circles, touch thresholds, and banner behavior.
- Search/KMZ competing click handlers: fixed as far as `drawing`/`inserting` goes; the imported-layer and search-pin bails are now called out explicitly.
- `VALID_SIDEBAR_PANELS`: fixed correctly in the spec text.

What the Sonnet rounds did not fully close was the second-order integration logic:
- the generic click handler’s exclusion set in `editing`
- the actual unit-rerender mechanism
- the true app.js edit count once `addPlaceholderSources()` is included
- the font-stack mismatch between the spec and real style files

## What R1-R4 missed
The main fresh-eyes misses are not new algorithms. They are integration seams and too-broad-claim problems.

- Editing-state click leakage: R1-R4 focused on `drawing`/`inserting` suppression. They missed that `editing` also needs protection, but by a different mechanism because `_ruler.isActive()` is intentionally false there.
- Rerender vs live-read: they fixed the source-of-truth bug, but not the render-trigger bug.
- Style-hook accounting: they required `addPlaceholderSources()` but did not propagate that requirement into the app.js insertion-count and merge-risk accounting.
- Font fallback: they asserted Metropolis availability, but did not compare the ruler spec’s single-font stack against the actual two-font pattern in shipped style JSON.
- Terrarium guard rails: they corrected the formula but left the no-data/impossible-value path underspecified.
- Checklist rigor: they expanded the manual gate but still left several items subjective enough to self-pass.
- Future-proofing language: they accepted the “KMZ-serializable” phrase without narrowing it to what the state shape really supports.
- Secondary lenses: i18n boundary, future label-sanitization rule, and browser-history non-goal all remain implicit.

## Recommended spec changes
1. In §A “Minimal touch to existing files”, update the app.js inventory to include:
- one edit in `addPlaceholderSources()` for `_ruler.reattachSources(map)`
- one edit in the generic click handler’s feature-hit exclusion list for ruler layers in `editing`
- optionally one insert in the units handler if you choose explicit `geographica:units-changed` dispatch

2. In §B “State machine” around the `editing` row and `isActive()` contract, add:
- “Vertex-clicks in `editing` are claimed by ruler and MUST NOT reach reverse-geocode. The generic click handler excludes ruler layers from its `queryRenderedFeatures()` gate.”

3. In §A “Imperial/metric handling”, replace “next render tick” with a real contract:
- either `document.dispatchEvent(new CustomEvent('geographica:units-changed', ...))` from the existing units handler
- or direct radio-input subscriptions from `ruler.js`

4. In §D layer definition and pitfalls, change the font stack to:
- `text-font: ['Metropolis Regular', 'Noto Sans Regular']`

5. In §E.3 decode logic, add a guard:
- alpha-zero => `null`
- decoded values outside plausible DEM bounds => `null`
- impossible samples contribute to coverage gaps, not min/max

6. In §Testing, add tests for:
- LRU eviction
- rAF drag coalescing
- multitouch drag cancel
- unit-toggle rerender integration
- the fourth click-suppression path in `editing`

7. In the manual checklist, rewrite subjective lines as explicit pass/fail assertions.

8. In the non-goals / state-shape language, narrow “KMZ-serializable” to “geometry-exportable to minimal KML/KMZ”.

9. Rename `test_terrain_rgb.js` to something that does not reintroduce the already-fixed encoding confusion.

## Plan-readiness assessment
v2 should not ship as-is and should not be the implementation-plan baseline. It needs a v3 spec revision first.

The good news: the remaining issues are concentrated and fixable. The bad news: the top one is a core editing-path integration bug, and several others sit exactly where Geographica tends to regress later: glue code, style-hook accounting, and tests that validate abstractions but not the real event path. If this were implemented from v2 unchanged, expect at least one “tap vertex, popup opens too” bug and at least one “units changed but ruler text stayed stale until next interaction” bug.
