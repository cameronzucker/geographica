---
round: 4
angle: Subagent executability
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-20
agent: alder
---

# Round 4 adversarial review — Nav voice TTM spec, subagent-executability lens

Reviewing `/home/administrator/Code/geographica/docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md`
as a subagent who received a plan derived from this spec with NO prior
conversation context. Goal: flag every spot where I'd either (a) get stuck,
(b) silently pick a wrong interpretation, or (c) ship a bug because the spec
defers to "obvious" convention that isn't actually established in the
codebase.

Cross-checked against: `frontend/navigation.js` (primary target of edits),
`frontend/tests/engine/navigation.test.mjs`, `frontend/tests/engine/test_runner.mjs`,
`docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md` (the sibling
spec this one composes with).

---

### F4.1 — Line number citations throughout will rot the moment any edit lands

**Severity:** MUST-FIX
**Ambiguity location:** §4.2 tail (`navigation.js:559`), §4.3 header
(`navigation.js:357-411`), §4.4 (`navigation.js:343-351`), §4.5 (`navigation.js:173`,
`lines 744 and 842`), §4.6 header (`navigation.js:891-895`), §4.3 "Key
differences" bullet 5 (`navigation.js:343-351`), §4.3 inline comment
("see frontend/navigation.js:396-405 of the current source"), §8 item 1
(`lines 42-67 of the current source`), §4.1 deletion block
(lines 42-57 of `e63f6d9` — also wrong: the BAND-AID block in live code
currently spans 42-67, not 42-57).

**Facts from codebase:**
- `announce()` is at `frontend/navigation.js:343-351` as claimed — OK today.
- `checkVoice()` is at `frontend/navigation.js:357-411` as claimed — OK today.
- `lastAnnouncementTime` declaration is at `frontend/navigation.js:173` — OK today.
- Reset/applyReroute references to `lastAnnouncementTime`: actually at
  `navigation.js:744` (reset) and `navigation.js:842` (applyReroute) — OK today.
- `window._geographicaNavEngineInternals` is at `navigation.js:891-895` — OK today.
- BAND-AID block comment is at `navigation.js:42-67` (the spec §4.1 says
  "lines 42-57 of `e63f6d9`" — **inconsistent internally** with §8 which
  says "lines 42-67 of the current source." 42-67 is correct; 42-57 in §4.1
  is a typo that will direct the implementer to delete only half the
  comment block and leave a dangling 10-line fragment.)

**Why these will rot:** The TTM work itself constitutes a large edit to
`navigation.js`. The subagent executing Task 1 (say, "add new constants")
will shift all line numbers below the insertion point by ~15 lines. By
Task 3, the `navigation.js:357-411` reference for `checkVoice()` is wrong,
the `navigation.js:891-895` reference for the test hook is wrong, and the
subagent for Task 4 is reading the spec with stale coordinates. Plan-author
subagents typically don't re-verify line numbers when transcribing the spec
into tasks.

**Two valid interpretations at Task 3+:**
- A) Trust the spec's line numbers, apply `Edit` at the cited range,
  misfire because the code at those lines is no longer what the spec
  claims.
- B) Search by content (`grep -n "function checkVoice"`), which works, but
  the subagent has now lost trust in every line citation in the spec.

**Subagent most likely to pick:** A on the first pass because the
`frontend/navigation.js#L357-L411` anchor in §4.3 looks authoritative.
Anchored links to line ranges are the worst kind of rot — they read like a
guarantee.

**What the spec should say explicitly:** Replace every line-number
reference with a search-by-content reference. Concretely:

- §4.2 "immediately after the existing line `lastSpeed = gpsSpeed;` (around
  navigation.js:559)" → "immediately after the existing `lastSpeed =
  gpsSpeed;` assignment in the `tick()` function (search for the exact
  string `lastSpeed = gpsSpeed;`)".
- §4.3 "Replaces [frontend/navigation.js:357-411]" → "Replaces the entire
  body of `function checkVoice(snap) {` (the function starts at the
  `// ─── Voice announcements ───` section header and ends at its matching
  `}`)".
- §4.3 bullet 5 "The 10-line function at `navigation.js:343-351`" → "The
  10-line `announce()` helper function defined immediately before
  `checkVoice` in the `// ─── Voice announcements ───` section".
- §4.4 "[navigation.js:343-351] becomes dead" → "The `announce(text, key)`
  helper becomes dead. Find it by searching for `function announce(text,
  key) {`".
- §4.5 "declared around navigation.js:173" → "declared in the `// Voice`
  state block alongside `announcedSet`; search for `var
  lastAnnouncementTime = 0;`".
- §4.5 "lines 744 and 842 of current source" → "in both `reset()` (search
  for the block of `announcedSet = {};`) and `applyReroute:` (search for
  the comment `// Full reset: old keys refer to a route that no longer
  exists.`)".
- §4.6 "[navigation.js:891-895]" → "the `window._geographicaNavEngineInternals`
  assignment near the end of the IIFE (search for
  `_geographicaNavEngineInternals`)".
- §8 item 1 "lines 42-67 of the current source" — keep this but add "search
  for the block comment starting with `// BAND-AID (2026-04-20`" and
  update §4.1 from "lines 42-57 of `e63f6d9`" to match 42-67 (or better,
  drop the numeric range entirely).

---

### F4.2 — §4.1 deletes 4 constants but §8 enumerates a different list

**Severity:** MUST-FIX
**Ambiguity location:** §4.1 "Deleted" block vs §8 item 1.

**Facts from the spec:**

§4.1 "Deleted" lists:
1. `VOICE_THRESHOLDS`
2. `VOICE_COOLDOWN`
3. `VOICE_SPEED_GATE`
4. `VOICE_NEAR_ANNOUNCE_DISTANCE`

§8 item 1 says "Delete `VOICE_THRESHOLDS`, `VOICE_COOLDOWN`,
`VOICE_SPEED_GATE`, `VOICE_NEAR_ANNOUNCE_DISTANCE` constants and the large
BAND-AID block comment (lines 42-67 of the current source)."

§8 item 2-4 add:
- The test `B1 band-aid: voice tiers capped at 2 per costing (remove when
  TTM ships)`
- `lastAnnouncementTime` state variable + references in `reset()` and
  `applyReroute()`
- `announce()` helper function

**Missing from BOTH lists (but implicitly required by §4.6):**
- Update (not strictly delete) `window._geographicaNavEngineInternals` —
  the current shape exposes `VOICE_THRESHOLDS`, `VOICE_COOLDOWN`,
  `VOICE_SPEED_GATE`. §4.6 rewrites the shape but the deletion checklist
  doesn't mention this. A subagent who treats §8 as authoritative will
  delete the constants but leave the test hook referencing them,
  producing a `ReferenceError: VOICE_THRESHOLDS is not defined` at module
  load time.
- The BAND-AID block comment itself (not a constant but a multi-line
  comment currently at navigation.js:42-67). §4.1 footnotes it ("along
  with the large BAND-AID block comment (lines 42-57 of `e63f6d9`)") but
  §8 includes it in item 1 with different line numbers (42-67). Two
  different line ranges cited for the same comment.

**Subagent most likely to do:** Work from §8 as the authoritative
deletion checklist (it's called out as "in the same PR" and reads like a
pre-merge checklist). §8 item 1 says "constants and the large BAND-AID
block comment" — OK, so the comment is covered. But the test hook update
is in §4.6 in the "Design" section, not in the deletion checklist.
Subagent deletes constants, gets a module-load crash in the test harness
because `_geographicaNavEngineInternals: { VOICE_THRESHOLDS: VOICE_THRESHOLDS,
... }` still references the deleted identifier.

**What it should say explicitly:** Unify §4.1 "Deleted" and §8 into one
authoritative checklist. Proposed §8 rewrite:

> ## 8. Band-aid removal — complete deletion checklist
>
> All of the following must land in the same PR as the TTM constants
> are added. The order below avoids intermediate broken states:
>
> 1. **Add** new constants (§4.1 "New") and new state (§4.2 "New state").
> 2. **Add** new helpers (`pushSpeedSample`, `speedMedian`).
> 3. **Rewrite** `checkVoice()` (§4.3) — the new body references the new
>    constants, which are now defined.
> 4. **Rewrite** `window._geographicaNavEngineInternals` (§4.6) — point
>    at new constants, drop old ones.
> 5. **Delete** `announce()` helper function.
> 6. **Delete** old constants: `VOICE_THRESHOLDS`, `VOICE_COOLDOWN`,
>    `VOICE_SPEED_GATE`, `VOICE_NEAR_ANNOUNCE_DISTANCE`.
> 7. **Delete** `lastAnnouncementTime` state variable declaration + two
>    references (in `reset()` and the `applyReroute:` method body).
> 8. **Delete** the BAND-AID block comment (search for `// BAND-AID
>    (2026-04-20`).
> 9. **Delete** the test `B1 band-aid: voice tiers capped at 2 per
>    costing (remove when TTM ships)` in
>    `frontend/tests/engine/navigation.test.mjs`.
> 10. **Update** the test `applyReroute clears announcedSet and
>     lastAnnouncementTime` (navigation.test.mjs:30) — the test name
>     mentions `lastAnnouncementTime`, and its failure message at line 72
>     references it verbatim. Either rename the test to `applyReroute
>     clears announcedSet and speedSamples` and update the assertion to
>     also check `_getSpeedSamples()` length, OR leave the test name and
>     drop the `lastAnnouncementTime` mention from the failure message.

Item 10 is NOT in §8 currently. The spec doesn't realize that an
existing live test mentions `lastAnnouncementTime` by name and will read
as stale after the deletion. See F4.8 for more.

---

### F4.3 — New constants have 10 plausible insertion points and no guidance

**Severity:** SHOULD-FIX
**Ambiguity location:** §4.1 "added at the top of the IIFE, alongside the
existing constants."

**Facts from codebase:** `navigation.js:15-67` is the constants block.
Within it:
- 15-19: math constants (DEG2RAD, EARTH_RADIUS)
- 21-29: off-route / reroute constants (OFF_ROUTE_*, REROUTE_*)
- 30-31: arrival constants (ARRIVAL_*)
- 32: HEADING_SPEED_GATE
- 33-34: GPS / DR constants
- 35-38: snap constants
- 39: SPEED_HISTORY_WINDOW
- 41-57: BAND-AID block comment
- 58-62: VOICE_THRESHOLDS
- 64: NEXT_AFTER_NEXT_DISTANCE
- 65-67: VOICE_COOLDOWN, VOICE_SPEED_GATE, VOICE_NEAR_ANNOUNCE_DISTANCE

"Alongside the existing constants" is true of 10+ possible locations.

**Two valid interpretations:**
- A) Insert at the very top, before DEG2RAD. Bad — violates the "math
  first" visual grouping.
- B) Insert in the voice section (lines 41-67), which is the obvious
  topical match. But that entire block is being deleted in the same PR.
  Net result: VOICE_TTM, VOICE_DISTANCE_FLOOR, MIN_SPEED_FLOOR,
  SPEED_WINDOW_SIZE replace the deleted VOICE_THRESHOLDS/etc block, with
  NEXT_AFTER_NEXT_DISTANCE preserved.
- C) Insert after SPEED_HISTORY_WINDOW on line 39, grouping speed-related
  constants together. Then the voice-tier constants remain in their own
  section later. Defensible but splits voice constants into two sections.
- D) Insert at the bottom of the constants block, as a new "Voice TTM"
  section. Acceptable but creates visual asymmetry with the existing
  (now-deleted) voice section.

**Subagent most likely to pick:** D (append to end, most additive) OR B
(replace the deleted block in place, most topically correct). Without
guidance, the plan-authoring subagent will pick one; the executing
subagent might pick a different one based on their reading of the spec.

**What it should say explicitly:** "Insert the new constants in place of
the deleted voice section. Specifically: after deletion of the BAND-AID
block comment, `VOICE_THRESHOLDS`, `VOICE_COOLDOWN`, `VOICE_SPEED_GATE`,
and `VOICE_NEAR_ANNOUNCE_DISTANCE`, add the new `VOICE_TTM`,
`VOICE_DISTANCE_FLOOR`, `MIN_SPEED_FLOOR`, `SPEED_WINDOW_SIZE` at the same
location (currently lines ~41-67, post-deletion the gap). Retain the
`NEXT_AFTER_NEXT_DISTANCE = 500;` declaration in place. A new 3-line
header comment `// Voice announcements — time-to-maneuver model` above
the block is the only new comment; no multi-paragraph rationale comment
is needed (the spec is the rationale)."

---

### F4.4 — `pushSpeedSample` / `speedMedian` scope unspecified

**Severity:** SHOULD-FIX
**Ambiguity location:** §4.2 "New helpers" code block.

**Facts from codebase:** The IIFE at `navigation.js:12-897` contains:
- Module-scope top-level `function` declarations (like `haversine`,
  `bearing`, `projectOntoSegment`, `snapToRoute`, `announce`, `checkVoice`)
- Module-scope `var` state declarations (like `route`, `state`,
  `speedHistory`, `announcedSet`)

The spec's §4.2 says "**New helpers:**" and gives function bodies but
does not specify whether they are:
- A) Top-level function declarations inside the IIFE (sibling to
  `announce`, `checkVoice`). Closes over `speedSamples`,
  `MIN_SPEED_FLOOR`, `SPEED_WINDOW_SIZE` implicitly via module scope.
- B) Nested inside `checkVoice()` (the only caller, arguably).
- C) Exposed on `GeographicaNav` for test introspection.

**Subagent most likely to pick:** A (matches neighbor conventions), and
this is correct. But the spec doesn't say so. A subagent with zero
context might pick B to "minimize public surface area," which (a) creates
a closure over `speedSamples` that resets on every `checkVoice` call
(breaking outlier rejection), and (b) moves `pushSpeedSample` away from
`tick()` where it must be invoked.

**What it should say explicitly:** Add a sentence at the top of §4.2:
"All speed-smoothing helpers (`pushSpeedSample`, `speedMedian`) are
top-level function declarations inside the IIFE, sibling to the existing
`announce` / `checkVoice` declarations. They close over the module-scope
`speedSamples` array. `pushSpeedSample` is called from `tick()`;
`speedMedian` is called from `checkVoice()`."

---

### F4.5 — `speedMedian()` return type contract on empty buffer is under-specified

**Severity:** SHOULD-FIX
**Ambiguity location:** §4.2 `speedMedian()` body.

**Facts from spec body:**
```js
if (speedSamples.length === 0) return MIN_SPEED_FLOOR;
```
This returns 1.0 when empty. OK.

**But §4.3 then wraps it in another floor:**
```js
var speed = Math.max(speedMedian(), MIN_SPEED_FLOOR);
```

**Ambiguity:** Why does the caller need `Math.max` if the helper already
floors on empty? The answer the spec doesn't state: because
`speedSamples` could contain `[0]` — one sample of speed 0 from a
stationary GPS — and `speedMedian()` returns 0. Then the caller's
`Math.max(0, 1.0) = 1.0` rescues the divide-by-zero. The helper only
floors the EMPTY case, not the ZERO case.

**Two valid interpretations by a subagent reading §4.2 in isolation:**
- A) `speedMedian` floors empty → 1.0 but returns raw samples otherwise
  (could return 0). Caller must additionally floor.
- B) `speedMedian` floors both empty AND zero cases. Caller's
  `Math.max` is defensive redundancy.

**Subagent most likely to pick:** B for "simplicity" and delete the
`Math.max` in the caller as "already handled." TTM math now divides by 0
at any red light where GPS reports 0 m/s. Test at speed=0 (I3 test)
returns `Infinity` for TTM, which still yields "far does not fire" but
the behavior is fragile and violates I3's "TTM→∞ from speed clamped to
1.0" specification.

**What it should say explicitly:** In §4.2, add a contract block before
the function body:

```
// speedMedian() contract:
//   - returns MIN_SPEED_FLOOR (1.0) when speedSamples is empty
//   - returns the true median of 1, 2, or 3 samples otherwise
//   - CAN return 0 if all samples are 0 (stationary GPS);
//     callers MUST apply their own MIN_SPEED_FLOOR floor before using
//     the value as a divisor.
```

And in §4.3, a comment on the `Math.max(speedMedian(), MIN_SPEED_FLOOR)`
line: "// Floor again — speedMedian can return 0 for stationary GPS."

---

### F4.6 — `simulateApproach` return shape is under-specified

**Severity:** SHOULD-FIX
**Ambiguity location:** §6.1 "returns `{count, prompts}`."

**Facts from existing test conventions:** The in-repo voice test at
`navigation.test.mjs:30-74` accumulates into an array
`voiceFires.push({ text: voiceText, at: Date.now() });`. So the existing
convention is `{ text, at }` with wallclock timestamps. The spec doesn't
match this.

**Ambiguities:**
- `count` — an integer, clear. OK.
- `prompts` — array of what? Subagent interpretations:
  - A) `string[]` — just the texts. Loses the ability to assert on
    timing (§6.1 "parameterizes over speeds" implicitly wants
    per-prompt timing).
  - B) `Array<{text: string}>` — single-key objects, future-extensible.
  - C) `Array<{text: string, tick: number}>` — text + which synthesized
    tick fired it. Needed to assert "prompt N fired at tick K."
  - D) `Array<{text: string, at: number, maneuverIdx: number}>` —
    matches existing convention + adds maneuver attribution. Needed for
    §6.4 (asserts "exactly 3 near-tier prompts, one per maneuver").

**Subagent most likely to pick:** A (simplest). §6.4 then needs to
assert "each prompt uses `verbal_pre_transition_instruction`" — which
works on `string[]` only by string-matching. But §6.4 also requires
"exactly 3 voice prompts fired (one near-tier per maneuver, no far-tier
prompts — D1 suppression holds)" which requires knowing WHICH maneuver
each prompt was for. With `string[]`, the subagent has to infer from
the text content (e.g., "Turn left onto Main Street" → maneuver 1),
which is brittle if the fixture happens to have similar strings.

**What it should say explicitly:** In §6.1:

> The helper `simulateApproach({speed, entryDist, costing, steps})`
> synthesizes GPS ticks and returns:
>
> ```js
> {
>   count: number,              // total prompts fired
>   prompts: Array<{
>     text: string,              // the voice text
>     tick: number,              // which synthesized tick index fired it
>     maneuverIdx: number,       // route.maneuvers[idx] the prompt was for
>     tier: 'far' | 'near'       // which tier fired (derived from announcedSet key)
>   }>
> }
> ```
>
> The `tier` discrimination requires a test-internal helper that compares
> the fired `text` against `m.verbal_pre_transition_instruction` (near)
> vs `m.verbal_transition_alert_instruction` (far). Implement in the
> test file, not as a navigation.js export.

---

### F4.7 — No route fixture referenced for §6 tests; existing fixture has wrong costing shape

**Severity:** SHOULD-FIX
**Ambiguity location:** §6.1, §6.4.

**Facts from codebase:** `test_runner.mjs:50-88` exports
`fixtureRouteWithTwoTurns()`. That fixture has `costing: 'auto'` and
specific maneuver shapes. §6.4 requires a 3-maneuver route with
maneuvers spaced 30m apart — does not exist. §6.1's 3-costing test
matrix requires fixtures for `auto`, `bicycle`, `pedestrian` — only
`auto` exists.

**Two valid interpretations:**
- A) Subagent adds new fixtures (`fixtureDenseCluster()`,
  `fixtureBicycleRoute()`, `fixturePedestrianRoute()`) to test_runner.mjs.
- B) Subagent clones + mutates `fixtureRouteWithTwoTurns()` inline per
  test. DRY violation; the Villa Rita fixture in particular is
  substantial (3 close maneuvers, specific verbal instructions for D1
  chain assertion).
- C) Subagent hard-codes route objects in each test body. Verbose,
  error-prone.

**Subagent most likely to pick:** C first for speed; then when §6.4's
assertions get complicated, refactors to A halfway through. Either way,
without guidance the 12+ test cells in §6.1 end up with slightly
different fixture shapes and drift from each other.

**What it should say explicitly:** In §6.1, add:

> **Fixtures:** Add three new fixtures to `frontend/tests/engine/test_runner.mjs`
> (sibling to the existing `fixtureRouteWithTwoTurns`):
>
> - `fixtureCostingRoute(costing)` — parametric single-maneuver route,
>   takes `costing ∈ {'auto', 'bicycle', 'pedestrian'}` and returns
>   a route with that costing. Used by §6.1 per-costing assertions.
> - `fixtureDenseClusterRoute()` — 3 maneuvers spaced 30m apart with
>   `verbal_pre_transition_instruction` set distinctly per maneuver
>   (so §6.4 can assert on the exact text of each prompt). Used by §6.4.
> - `fixtureOutlierRoute()` — single-maneuver route at 300m distance,
>   designed for §6.2 outlier-rejection baseline. Used by §6.2.
>
> Each fixture must populate `totalDistance`, `totalTime`, and
> `remainingWaypoints: []`, matching `fixtureRouteWithTwoTurns`'s shape.

---

### F4.8 — Existing test `applyReroute clears announcedSet and lastAnnouncementTime` becomes stale-named

**Severity:** MUST-FIX
**Ambiguity location:** §9 files-changed list + §6 test strategy.

**Facts from codebase:** `navigation.test.mjs:30` has a test whose name
literally includes `lastAnnouncementTime`:
```js
test('applyReroute clears announcedSet and lastAnnouncementTime', async (t) => {
```
And at line 72, a failure message:
```js
'announcement should re-fire on new route; was suppressed — announcedSet/lastAnnouncementTime not cleared'
```

Under TTM, `lastAnnouncementTime` is deleted. The test still passes
(because it asserts on re-firing, not on the variable's existence), but
its name now references a variable that doesn't exist in the source.
Future greps for `lastAnnouncementTime` land on a stale test that
doesn't actually test what its name says.

**Two valid interpretations:**
- A) Subagent touches only the test listed for deletion (B1 band-aid
  test at line 190). Leaves this test untouched. Stale name.
- B) Subagent recognizes this test as related, renames it to
  `applyReroute clears announcedSet and speedSamples`, updates
  assertion to also check `win._geographicaNavEngineInternals._getSpeedSamples()`
  is empty post-reroute. Correct, but spec doesn't prompt this.

**Subagent most likely to pick:** A. §9 lists "delete band-aid regression
guard" but does not list "rename / extend the lastAnnouncementTime
test." The subagent has no signal to update it.

**What it should say explicitly:** Add to §6.3 (Reroute state clearing):

> **Also update** the existing test `applyReroute clears announcedSet
> and lastAnnouncementTime` at `navigation.test.mjs:30`:
> - Rename to `applyReroute clears announcedSet and speedSamples`.
> - Failure message at the final assertion: change
>   `announcedSet/lastAnnouncementTime not cleared` to
>   `announcedSet/speedSamples not cleared`.
> - Add a second assertion after the reroute:
>   `assert.equal(win._geographicaNavEngineInternals._getSpeedSamples().length,
>   0, 'speedSamples must be empty after applyReroute')` — BUT only after
>   feeding enough pre-reroute GPS ticks to actually populate the buffer.

---

### F4.9 — Edit ordering is not specified; intermediate states can break the test harness

**Severity:** SHOULD-FIX
**Ambiguity location:** §8 enumerates deletions but doesn't give a
dependency-safe execution order.

**The problem:** If a subagent follows §8 in listed order:

1. Delete `VOICE_THRESHOLDS`, `VOICE_COOLDOWN`, `VOICE_SPEED_GATE`,
   `VOICE_NEAR_ANNOUNCE_DISTANCE`. → `announce()` still references
   `VOICE_COOLDOWN`, `checkVoice()` still references the other three.
   `navigation.js` is now a `ReferenceError` at module-load time. Test
   harness in `test_runner.mjs:41` calls
   `runInContext(code, ctx, {filename: 'navigation.js'})` which will
   throw at load time. Every test in the file errors, not just voice
   tests.
2. Delete the B1 test. → Can't run tests to validate the previous step.
3. Delete `lastAnnouncementTime`. → dead code, no immediate fallout.
4. Delete `announce()`. → now the VOICE_COOLDOWN reference is gone, BUT
   `checkVoice()` still calls `announce(text, key)` at
   `navigation.js:408`. → another ReferenceError at runtime.

Even if the subagent is careful and does the §4.3 rewrite of
`checkVoice()` first, they have to land ALL the new code BEFORE deleting
any old code, or they're in a broken tree.

**Subagent most likely to do:** Follow §8 literally in listed order,
land broken intermediate commits.

**What it should say explicitly:** Add §8.0 "Execution order":

> ## 8.0 Execution order (task sequencing in the plan)
>
> To avoid intermediate broken states, the plan must sequence tasks in
> this order. Each of these is one or more commits; none should be
> reordered.
>
> 1. **Add NEW**: new constants (§4.1), new state (`speedSamples`),
>    new helpers (`pushSpeedSample`, `speedMedian`) — all additions,
>    no deletions. navigation.js still compiles; all existing tests
>    still pass (new code is unreferenced dead code).
> 2. **Wire**: `pushSpeedSample(gpsSpeed)` added to `tick()`, and
>    `speedSamples = []` added to `reset()` and `applyReroute:`.
>    Existing tests still pass (new side effects are benign).
> 3. **Rewrite `checkVoice()`**: replace the full function body with the
>    TTM version (§4.3). Existing `announce()` helper is now unreferenced
>    but still defined. The B1 band-aid test now fails (the new
>    checkVoice reads `VOICE_TTM`, not `VOICE_THRESHOLDS`) — this is
>    expected; it's about to be deleted.
> 4. **Rewrite test hook** (§4.6): update
>    `_geographicaNavEngineInternals` to expose new constants; the B1
>    test still references `internals.VOICE_THRESHOLDS` which is now
>    `undefined`. Test fails cleanly (it was about to be deleted anyway).
> 5. **Delete old**: `announce()`, old constants (`VOICE_THRESHOLDS`,
>    `VOICE_COOLDOWN`, `VOICE_SPEED_GATE`, `VOICE_NEAR_ANNOUNCE_DISTANCE`),
>    `lastAnnouncementTime` state + two references, BAND-AID block
>    comment. After this commit, navigation.js has no references to
>    deleted symbols. Tests: B1 test still exists and fails.
> 6. **Delete B1 test**: delete `test('B1 band-aid: voice tiers capped
>    at 2 per costing (remove when TTM ships)', ...)` in
>    navigation.test.mjs. Rename the `applyReroute clears announcedSet
>    and lastAnnouncementTime` test per F4.8.
> 7. **Add new tests**: §6.1 TTM matrix, §6.2 outlier rejection,
>    §6.4 Villa Rita synthetic.
> 8. **Verify**: `cd frontend && node --test tests/engine/` green.

---

### F4.10 — Commit scope unclear: "the PR" could be 1, 2, or 8 commits

**Severity:** SHOULD-FIX
**Ambiguity location:** §8 item 5 ("Commit message: must include
'closes B1, removes 2026-04-20 band-aid (`e63f6d9`)' in the body. Per
CLAUDE.md conventions, include `Agent: alder` trailer.") vs §10 item 6
("Integration review pre-merge.").

**The problem:** §8 says "the commit message" (singular), which
implies one squash commit. §8.0 (once added per F4.9) describes 8
sequenced steps, each naturally a separate commit for review
granularity. CLAUDE.md "Commit and release discipline" prefers scoped
commits (`feat(nav): ...`) for localized changes but this spec spans
8+ distinct steps in one subsystem.

**Two valid interpretations:**
- A) Subagent executes all 8 steps and amalgamates into one squash
  commit at the end. Fine for ship, but lost granular review history.
- B) Subagent makes 8 commits, one per §8.0 step. Only the FINAL commit
  mentions "closes B1, removes band-aid (e63f6d9)". First 7 commits
  have no such footer — plan-authoring subagent may copy-paste the
  §8 item 5 instruction into EVERY task, producing 8 commits that each
  claim to "close B1."
- C) Subagent makes 8 commits and only the deletion commit (§8.0 step 5
  or 6) mentions "closes B1" — the others are scoped `feat(nav): add
  TTM constants`, `feat(nav): wire speed smoothing`, etc.

**Subagent most likely to pick:** B if working from a plan where each
task has identical commit-footer instructions. CLAUDE.md's conventional
commits table in `CONTRIBUTING.md` would treat each additive commit as
`feat(nav):` and the deletion as `refactor(nav):`.

**What it should say explicitly:** Add §8.1:

> ## 8.1 Commit shape
>
> The work lands as a sequence of conventional commits matching the
> §8.0 order. Only the deletion-commit body includes "closes B1,
> removes 2026-04-20 band-aid (`e63f6d9`)". All commits include
> `Agent: alder` and `Co-Authored-By:` trailers per CLAUDE.md.
>
> Recommended commit messages (one per §8.0 step):
>
> 1. `feat(nav): add TTM constants and speed-smoothing state`
> 2. `feat(nav): wire pushSpeedSample into tick and reset paths`
> 3. `feat(nav): rewrite checkVoice with TTM thresholds and D1 suppression`
> 4. `feat(nav): update _geographicaNavEngineInternals for TTM`
> 5. `refactor(nav)!: remove VOICE_THRESHOLDS band-aid` — this is the
>    commit whose body says "closes B1, removes 2026-04-20 band-aid
>    (`e63f6d9`)". The `!` + `BREAKING CHANGE:` footer flags the
>    test-hook shape change per CLAUDE.md convention.
> 6. `test(nav): remove B1 band-aid regression guard, rename reroute test`
> 7. `test(nav): add TTM voice matrix, outlier rejection, Villa Rita cluster`

---

### F4.11 — Architecture diagram §3 misses the reroute/reset self-edge AND the stale-GPS checker

**Severity:** NICE-TO-HAVE
**Ambiguity location:** §3 ASCII diagram.

**Facts from codebase:**
- `startStaleChecker()` at `navigation.js:706-715` runs a 1 Hz interval
  that calls `deadReckonTick()` → `checkVoice(drSnap)` when GPS is
  stale. This is a SECOND entry into `checkVoice()` that §4.2 ignores —
  E7 acknowledges it but the architecture diagram doesn't show it.
- `reset()` and `applyReroute()` mutate the engine's own state — this
  is a self-edge from the engine box to itself. The current diagram
  shows them as exit arrows with the comment `speedSamples=[]
  announcedSet={}` but no control-flow direction.

**Two valid interpretations by a subagent building a mental model:**
- A) The diagram shows `checkVoice` as fired only from `tick()`. An
  implementer who trusts this misses E7 ("Dead-reckoning tick during
  GPS outage") and fails to write a test for it. Unit test coverage
  gap.
- B) The implementer reads §4.2 carefully, notices "Integration into
  `tick()`" but not "Integration into `deadReckonTick()`", and asks:
  should `pushSpeedSample` also fire during DR? The spec says no (E7
  "these do not update during DR") but the diagram doesn't reinforce it.

**Subagent most likely to do:** B — correct behavior but spends time
re-reading E7 to confirm. Low risk of breaking shipment.

**What it should say explicitly:** Update §3 diagram to show:

```
    GPS service         │ updateGPS(data)              │
                        │ ───────────────▶             │
                        │                              │
                        │  ┌────────────────────────┐  │
                        │  │  frontend/navigation.js │  │
                        │  │                        │  │
                        │  │  tick() — from GPS      │  │
                        │  │   ├─ pushSpeedSample    │  │
                        │  │   └─ checkVoice         │─┼──▶ onVoiceCb(text)
                        │  │                        │  │
                        │  │  deadReckonTick() — 1Hz │  │
                        │  │   └─ checkVoice (only)  │─┼──▶ onVoiceCb(text)
                        │  │        (no speed push)  │  │
                        │  │                        │  │
                        │  │  reset()/applyReroute() │  │
                        │  │   ↺ speedSamples = []   │  │
                        │  │   ↺ announcedSet = {}   │  │
                        │  └────────────────────────┘  │
```

---

### F4.12 — §10 process steps conflate spec-lifecycle vs plan-lifecycle gates

**Severity:** SHOULD-FIX
**Ambiguity location:** §10 items 2-8.

**The problem:** §10 lists 8 items. Items 1-3 are clearly
spec-lifecycle (write spec, review spec, v2 spec). Items 4-8 are
plan-lifecycle (write plan, execute, merge). But a subagent handed
"execute this spec" may reasonably treat §10 as their checklist and
re-run adversarial review rounds 1-6, producing redundant artifacts.

**Two valid interpretations:**
- A) Plan-authoring subagent reads §10, treats items 1-3 as "already
  done" (visible via git log / `dev/adversarial/*-ttm-r*.md` files) and
  items 4-8 as their scope. Correct.
- B) Plan-authoring subagent reads §10, reruns R1-R6 because "the spec
  says adversarial review must be done." Wastes 6 subagent-hours.
- C) Execution subagent (from the plan) reads §10 during the
  implementation task, gets confused about whether they should pause
  to produce R-files before editing code. Most likely: they skip the
  §10 content as "not my job."

**Subagent most likely to do:** C (execution subagent skips §10),
which is correct but unintentional.

**What it should say explicitly:** Reorder §10 or split it:

> ## 10. Process gates
>
> ### 10.1 Spec-lifecycle gates (already met or in progress at spec v2)
>
> 1. **v1 spec written** — done.
> 2. **R1-R6 adversarial reviews complete** — artifacts in
>    `dev/adversarial/2026-04-20-nav-voice-ttm-r{1..6}-*.md`.
> 3. **Spec v2** — incorporates MUST-FIX findings; revision history
>    lists rejected findings with rationale. Done before plan authoring.
>
> ### 10.2 Plan-lifecycle gates (for the plan author and executor)
>
> 4. **Implementation plan** authored via `superpowers:writing-plans`.
>    Output: `docs/superpowers/plans/2026-04-20-nav-voice-ttm-plan.md`.
> 5. **Subagent-driven execution** via
>    `superpowers:subagent-driven-development`. Each dispatch prompt
>    includes "You are agent `alder`".
> 6. **Integration review** pre-merge (via
>    `superpowers:requesting-code-review`).
>
> ### 10.3 Ship gates (human-in-the-loop)
>
> 7. **Runtime validation on live stack** — cam tests on pandora.
> 8. **§6.5 Villa Rita field re-drive** — ≤ 3 prompts for the 3-maneuver
>    cluster. This is THE ship-blocker.
> 9. **Merge `dev` → `main`** only after step 8.

This makes it unambiguous that the execution subagent's entry point is
§10.2 item 4, and §10.3 items 7-8 are human-gated not agent-gated.

---

## Summary

- **12 findings.**
- **Most ambiguous single spot:** F4.2 + F4.9 combined — the deletion
  checklist is incomplete AND has no safe execution order, creating a
  clear path to a broken-tree intermediate commit. A subagent following
  §8 in listed order will land `navigation.js` in an unloadable state
  (ReferenceError at `vm.createContext`) and propagate the breakage
  across every test in the file.
- **Runner-up:** F4.1 — every line number in the spec will rot the
  moment Task 1's additions ship. Nine of the twelve line citations will
  be wrong by Task 3 because the additions are upstream of the cited
  locations.
- **Pattern across findings:** the spec was written by someone with
  full codebase context who knew what `alongside the existing
  constants` and `the top of the IIFE` meant. A subagent without that
  context has 10+ plausible interpretations of each. Six of the twelve
  findings trace to under-specified "it's obvious where this goes"
  statements that aren't obvious at all when you're reading cold.
- **New hazard not in the voice-picker R4 review:** edit ordering
  (F4.9) — voice-picker is a new file, so there's no intermediate-broken-
  state risk. TTM is a in-place rewrite of an existing module with
  deletions + additions + reshapes, and the spec's §8 listing order
  produces a ReferenceError tree if followed literally. This is the
  single biggest delta between voice-picker executability and TTM
  executability.
