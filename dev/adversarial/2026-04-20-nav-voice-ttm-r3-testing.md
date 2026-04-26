---
round: 3
angle: Testing sufficiency and coverage gap hunt
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-20
agent: alder
---

# Round 3 — Testing strategy

Verdict up front: the TTM spec's §6 is **meaningfully stronger than the
nav-keep-awake spec's §6.1 equivalent** (it has a matrix, an invariant list,
a named cluster scenario, and an explicit manual ship gate). But on close
reading §6 hand-waves at exactly the contract boundaries where a subagent
will have to make decisions, and three invariants (I5, I7, I8) are asserted
without a matching cell in the §6.1 matrix. The §6.5 Villa Rita ship gate is
the single largest unmitigated risk: it is a one-shot human-driven regression
test with no recorded-GPX playback backstop, so a post-merge field regression
has no automated witness. The `simulateApproach` helper is under-specified
in a way that will let the implementer write tests that pass against the
new code but tell us nothing about the real engine's behavior under real
GPS input.

Against the six attack lenses in the prompt: six MUST-FIX, six SHOULD-FIX,
two NICE-TO-HAVE. Most dangerous coverage gap is **F3.4** (the
`simulateApproach` contract is ambiguous enough that it can be implemented
as a pure-function TTM calculator that never exercises `updateGPS`, leaving
the full tick() / snapToRoute() / findManeuverForSegment() path untested
for the matrix).

## Findings summary

- MUST-FIX: 6 (F3.1, F3.2, F3.4, F3.6, F3.7, F3.12)
- SHOULD-FIX: 6 (F3.3, F3.5, F3.8, F3.9, F3.11, F3.13)
- NICE-TO-HAVE: 2 (F3.10, F3.14)
- **Total: 14**

---

### F3.1 — Invariant I5 (outlier rejection) has no 2-outliers-in-3-window cell

**Severity:** MUST-FIX
**Claim/gap in spec:** §5 I5 claims "median-of-3 smoothing rejects 1 outlier
per window." §6.2 tests a single 50 m/s sample injected into a 10 m/s stream.
**Bug class that could ship:** Median-of-3 rejects **one** outlier but not
two. Real GPS outlier patterns are not isolated: a multipath bounce at a
highway overpass typically produces two or three consecutive bad samples
before the receiver recovers. If `speedSamples` holds `[50, 50, 10]`, the
sorted median is `50` — far-tier TTM fires at `dist/50 = 30s` when the
vehicle is actually doing 10 m/s (so 30s-of-TTM = 300m distance, not 900m).
The prompt fires THREE TIMES TOO FAR from the maneuver. Invariant I5 does
not hold under this failure mode, and the §6.2 test as written does not
exercise it. Worse, §5 E1 "warmup" acknowledges that `speedSamples.length
=== 1` at route-start means the single value governs — but there is no
test for what happens when the warmup sample is itself the outlier AND
the next two samples come in before the threshold crosses.
**Proposed fix:** Add two cells to §6.2:
**Test specification:**
```
Test 6.2b — two consecutive outliers in a 3-window:
  Input: steady 10 m/s stream, distance 300 m from maneuver.
  Inject samples [50, 50] at ticks T and T+1 while the 10-m/s-baseline
  stream continues at T+2, T+3, T+4.
  Expected: far-tier prompt fires between T+3 and T+5 (after the outliers
  roll out of the window), NOT at T or T+1. Document the known-bad
  behavior if the median lets one through: record the exact tick count
  difference as a regression number so a future upgrade to median-of-5
  can be a measurable improvement.

Test 6.2c — route-start outlier (warmup):
  Input: first GPS tick of new route is 50 m/s at 500 m from maneuver.
  Expected: a far-tier prompt MAY fire once (per E1); announcedSet locks;
  subsequent 10-m/s samples do NOT fire near-tier prematurely.
  Assertion: at most 1 premature prompt per route, per maneuver.
```

---

### F3.2 — `simulateApproach` contract is ambiguous; test-level vs integration-level unclear

**Severity:** MUST-FIX
**Claim/gap in spec:** §6.1 — "Use a helper `simulateApproach({speed,
entryDist, costing, steps})` that synthesizes GPS ticks and returns
`{count, prompts}`."
**Bug class that could ship:** The helper signature is open to two
implementations with very different coverage:
1. **Pure-function interpretation:** helper computes `ttm = entryDist /
   speed`, walks tier conditions, returns a simulated prompt count. This
   tests the TTM *math* but never exercises `nav.updateGPS()`, which
   means `snapToRoute()`, `findManeuverForSegment()`, the `distanceToManeuver`
   path, and the interaction between `speedSamples` and `lastSpeed` are
   **not covered by a single cell in the 48-cell matrix**. All the matrix
   proves is that §4.3's algebra is correct on paper.
2. **Integration interpretation:** helper builds a fixture route, calls
   `nav.start(route)` with a mocked window, then calls `nav.updateGPS(...)`
   `steps` times with synthesized ticks that walk the vehicle from
   `entryDist` to the maneuver. This gets full-path coverage but is
   ~10× more code to author and depends on a valid route fixture at the
   right shape.

A subagent without explicit guidance will pick (1) because it is
drastically easier. §6.4 Villa Rita synthetic is then the ONLY
integration-level cell — and its `begin_shape_index` / `end_shape_index`
need to be hand-computed for a 3-maneuver-30m-apart route, which is
fiddly enough that the subagent will likely default (1) for §6.4 too.
**Proposed fix:** Pin the contract in §6.1:
**Test specification:**
```
simulateApproach MUST be an integration-level helper:
  1. Builds a test route via an updated fixtureRouteWithTwoTurns(opts)
     accepting an `entryDist` parameter that sets the start coord so the
     vehicle begins `entryDist` meters from maneuver 1.
  2. Calls loadEngine() and nav.start(route).
  3. Feeds `steps` updateGPS() calls, each synthesizing a GPS position
     along the polyline at the current `speed` m/s. Tick interval = 1000 ms
     to match the real feedGPS() cadence.
  4. Collects onVoice() callbacks into `prompts`.
  5. Returns { count: prompts.length, prompts, finalSamples: internals._getSpeedSamples() }.

Cells that DO NOT use simulateApproach (e.g., a pure-math unit test for
VOICE_TTM table membership) are allowed but MUST be named differently
(e.g., `ttm_constants.test.mjs`) so the reviewer knows what coverage
each file provides.
```

---

### F3.3 — `lastAnnouncementTime` already removed but test file asserts it; test migration incomplete

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §6.6 "Existing tests that import `VOICE_THRESHOLDS`
fail loudly on undefined — desired. Update the band-aid regression test
by deleting it."
**Bug class that could ship:** The existing `applyReroute clears
announcedSet and lastAnnouncementTime` test at
`frontend/tests/engine/navigation.test.mjs:30` has `lastAnnouncementTime` in
its **name** and its **assertion message** ("announcement should re-fire on
new route; was suppressed — announcedSet/lastAnnouncementTime not cleared").
Under TTM, `lastAnnouncementTime` does not exist. The test body itself is
still meaningful (it asserts re-fire on reroute), but:
1. The test NAME is lying. A future dev greps for `lastAnnouncementTime`
   and finds this test, expecting it to exercise a nonexistent concept.
2. The assertion message references a nonexistent state variable, so
   when the test fails, the error message points at a ghost.
3. The test currently drives "approach at 40m at 10 m/s" which, under
   TTM, hits the **near-tier** (TTM = 4s ≤ 3s? no — 4s > 3s; but 40m
   ≤ 50m floor, so near fires via the floor trigger). Under D1 suppression,
   the far-tier also auto-marks. So the test's setup passes by luck, not
   by design. Small fixture edits (coord shift) silently break it.

§6 and §8 list "delete the band-aid regression guard" but DO NOT list
renaming / rewriting this pre-band-aid test.
**Proposed fix:** Add an explicit plan task (and mention in §6.6 / §8):
**Test specification:**
```
1. Rename test from `applyReroute clears announcedSet and lastAnnouncementTime`
   to `applyReroute clears announcedSet and speedSamples`.
2. Update assertion message to reference `speedSamples` + `announcedSet`.
3. Add an explicit assertion:
   assert.deepEqual(internals._getSpeedSamples(), [], 'speedSamples cleared on reroute');
   (Requires test-hook from §4.6.)
4. Audit the coord used for the approach. Current coord [-111.6405, 35.20]
   is ~40m from the maneuver. Under TTM at 10 m/s + 50m floor, this fires
   near-tier via floor, D1 auto-marks far. The test should either:
   (a) move the approach to ~600m outside the far tier (TTM=60s > 30s)
       so the far-tier fires BEFORE reroute clears state, or
   (b) document that it exercises near-via-floor and add a matching
       coord comment.
```

---

### F3.4 — Fake-timer infra deferred in spec §9; TTM tests do not need Date.now() mocked but spec leaves it ambiguous

**Severity:** MUST-FIX
**Claim/gap in spec:** §9 says "possibly add fake-timer helper if the TTM
tests need it." §6 says nothing about whether wall-clock time matters. The
2026-04-20 nav-keep-awake post-mortem flagged partial fake-timer deferral.
**Bug class that could ship:** TTM's algebra does not use `Date.now()`
directly — `ttm = dist / speed` has no time input. But:
1. `setTimeout` / `clearTimeout` IS used for `rerouteTimeoutId` and
   `staleChecker`. The existing test `reroute timeout clears
   lastRerouteTime for immediate re-reroute` (navigation.test.mjs:144)
   waits **10.5 seconds of real wall-clock time**. If §6.3 (reroute
   state clearing) follows that pattern, the TTM reroute test also burns
   10s of real time per run. Multiply by the §6.1 matrix's 12-48 cells
   and CI bloats.
2. `applyReroute` synchronously calls `tick(lastGPS)` at line 299 of the
   spec. But the SAME tick's speedSamples is empty (just cleared),
   `speedMedian` returns `MIN_SPEED_FLOOR = 1.0`, and `ttm = distToNext /
   1.0 = distToNext`. If distToNext to the new route's next maneuver is
   < 30s (i.e., < 30m numerically), **the far-tier fires immediately on
   reroute**. This is a legitimate behavior (E2 "GPS never arrives —
   one prompt at route start") but is not tested.
3. The §6.3 reroute test as currently described ("Drive an approach that
   fires one near-tier for maneuver 0. Invoke applyReroute. Assert
   announcedSet empty. The new route's first maneuver fires normally.")
   depends on `setTimeout`'s real-time behavior of `rerouteTimeoutId`.
   If the test doesn't mock time, it's fine. If §9 decides to add a
   fake-timer helper and the subagent applies it here, `applyReroute`'s
   internal `clearTimeout(rerouteTimeoutId)` may behave unexpectedly.

The spec should DECIDE: fake-timer infra is NOT needed for TTM unit tests.
**Proposed fix:**
**Test specification:**
```
§9 should say explicitly:
  "Fake-timer helper is NOT required for TTM tests. TTM algebra is
   time-free; the only wall-clock path is rerouteTimeoutId which is
   covered by the existing navigation.test.mjs:144 test pattern.
   DO NOT add a fake-timer helper as part of this PR — it is out of
   scope and can be revisited if the voice-picker spec (separate PR)
   needs it."

Then §6.3 explicitly says reroute test uses real `setTimeout` with
a short-circuit: capturedSeq from onReroute allows immediate
applyReroute() invocation WITHOUT waiting for the 10s timeout.
Pattern already in navigation.test.mjs:46-64; reuse directly.

Add §6.3b test: post-reroute E2 case:
  Input: applyReroute with new route where maneuver[1].shape is 15 m away.
  Expected: exactly 1 prompt fires on the immediate synchronous tick
  (far-tier via TTM-at-floor-speed, or near-tier via distance floor).
```

---

### F3.5 — Villa Rita synthetic (§6.4) vs real (§6.5) — maneuver-shape mismatch not addressed

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §6.4 "Synthesize a 3-maneuver route with maneuvers
spaced 30m apart...Exactly 3 voice prompts fired." §6.5 "re-drive the
Villa Rita → Costco...≤ 3 prompts."
**Bug class that could ship:** The synthetic uses hand-constructed maneuvers
with one `verbal_pre_transition_instruction` each. A real Valhalla response
for the Villa Rita detour may contain:
1. **Roundabout pairs:** Valhalla emits `maneuver_type 26` (roundabout-
   enter) immediately followed by `maneuver_type 27` (roundabout-exit).
   Both are voice-announceable. A 3-turn cluster that contains one
   roundabout becomes a 4-maneuver cluster that the synthetic's
   "exactly 3 prompts" assertion does not model. The synthetic passes;
   the field drive fires 4 prompts; the ship gate's "≤ 3" criterion
   FAILS post-merge because the synthetic was wrong.
2. **Continue-straight announcements:** At some reroute endpoints Valhalla
   emits a pro-forma `maneuver_type 1` "Continue on X" that the existing
   engine treats as announceable. The synthetic ignores these; the field
   may produce one.
3. **Per-maneuver `verbal_pre_transition_instruction` is sometimes
   empty:** production Valhalla returns `""` for some surface-street
   turn types. The synthetic always populates it, so the fallback to
   `m.instruction` is never exercised.
**Proposed fix:** The spec and plan must either:
(a) Capture a real Valhalla response for the Villa Rita → Costco route
    before writing the synthetic, save to
    `frontend/tests/engine/fixtures/villa_rita_detour.json`, and use it
    as the §6.4 input verbatim — real shape, real maneuver types.
(b) Loosen the §6.5 ship criterion to "≤ 3 prompts PER MANEUVER CLUSTER"
    where "cluster" is defined as consecutive maneuvers ≤ 500m apart, and
    document that roundabout-enter/exit pairs count as 1 cluster.
**Test specification:**
```
Preferred — (a). Add plan task BEFORE §6.4:
  1. Run Villa Rita → Costco detour request against
     /valhalla/route endpoint with costing=auto.
  2. Save response to frontend/tests/engine/fixtures/villa_rita_detour.json.
  3. Post-process: trim to only the rerouted cluster (the 3-maneuver
     dense section).
  4. Use as input to §6.4 synthetic test. Assert prompt count matches
     observed-in-field count (which §6.5 establishes, so §6.4 needs
     §6.5 done FIRST — or use the bug-hunt-shipped "9 prompts observed"
     as a baseline and assert the new count is ≤ 3).
```

---

### F3.6 — Unknown costing fallback untested; "truck" / "motor_scooter" silently route to auto

**Severity:** MUST-FIX
**Claim/gap in spec:** §4.3 line 174 `var costing = route.costing || "auto";`
and line 175 `var ttmPair = VOICE_TTM[costing] || VOICE_TTM.auto;`. §6.1
says "at minimum, one maneuver scenario per costing" — covers {auto, bicycle,
pedestrian}, the three defined in VOICE_TTM.
**Bug class that could ship:** Valhalla supports costing values beyond the
three in VOICE_TTM: `truck`, `motor_scooter`, `motorcycle`, `bus`,
`bikeshare`, `multimodal`, `transit`. If the frontend's routing UI ever
adds a "truck" profile (plausible for SAR vehicle support — Cameron has
mentioned this as future scope), every truck route silently uses auto's
`[30, 3]` thresholds. This may be fine (trucks drive similar speeds to
cars) or catastrophic (wide-turn radii + loaded-mass deceleration mean
a truck needs MORE advance notice than a car). The spec commits to the
fallback silently without testing it, so behavior is undocumented.
Worse: `route.costing` can be `undefined`, empty string `""`, or `null`
if Valhalla's response is malformed — the `|| "auto"` handles all three
but is not tested for any of them.
**Proposed fix:** Add §6.1-adjacent test:
**Test specification:**
```
Test 6.1c — unknown-costing fallback:
  Inputs: for costingValue in [undefined, null, "", "truck",
    "motor_scooter", "transit", "multimodal"]:
    Build route with route.costing = costingValue.
    simulateApproach({speed: 10, entryDist: 500, costing: costingValue,
      steps: 100}).
  Expected: each case produces the SAME prompt count and the same TTM
    thresholds as a costing="auto" call would (i.e., [30, 3], floor 50m).
  Also: `internals.VOICE_TTM["truck"]` is undefined (i.e., the fallback
    is the ONLY reason "truck" works; a typo like VOICE_TTM.auto → VOICE_TTM.auot
    would break auto AND truck simultaneously, so this is a worthwhile
    canary).
```
Document in §E an explicit edge case E10: "Unsupported costing falls back
to auto thresholds. If truck / motor_scooter becomes a real routing option
in the UI, add an explicit VOICE_TTM entry rather than relying on the
auto fallback."

---

### F3.7 — `announce()` deletion leaves no regression guard that cooldown-suppression is gone

**Severity:** MUST-FIX
**Claim/gap in spec:** §4.4 deletes `announce()`; §6 has no test for the
"no cooldown enforced" invariant. The §6.4 Villa Rita synthetic fires
3 prompts across 3 maneuvers — but its ticks are spaced in simulated
seconds apart, NOT in clock-milliseconds. So even with the old 5000ms
cooldown, 3 prompts at 30-m spacing at 10 m/s are spaced 3 seconds of
wall time apart (if each `updateGPS` is 1000ms of simulated tick), which
violates the cooldown and would BE SUPPRESSED by the old code. So §6.4
does test "cooldown is gone" **indirectly** — but only because of the
simulated-tick cadence, not by explicit assertion.
**Bug class that could ship:** A subagent reviewing diff sees `announce()`
gone but keeps the old `lastAnnouncementTime = now; if (now -
lastAnnouncementTime < 5000) return;` dead code somewhere else (e.g.,
accidentally inlined into checkVoice as a "safety net"). Tests pass because
the simulated-tick cadence never approaches 5000ms. Field drive then
exhibits the same 9-prompt disaster because the cooldown IS being enforced
at real-tick cadence.

§6 is missing a **regression-aversion test** for this specific removal.
**Proposed fix:** Add:
**Test specification:**
```
Test 6.7 — back-to-back prompts across adjacent maneuvers fire without
cooldown:
  Setup: 2-maneuver route, maneuvers at [0, 0] and [0.0003, 0] (~30m).
  Enter at [−0.0003, 0] (~30m before maneuver 1), speed 10 m/s,
  costing auto.
  Feed 5 updateGPS() calls in rapid succession with a mocked Date.now()
  that advances by 100 ms per tick (NOT 1000 ms). This simulates the
  "rapid-tick cadence" that a burst-replay test or high-freq GPS would
  produce.
  Expected: BOTH near-tier prompts fire (one for each maneuver), total
  count = 2. If cooldown is still live somewhere, count = 1.

Alternative (simpler): assert internal state directly:
  After checkVoice fires the first near-tier prompt, inspect the
  test-hook. Assert NO `lastAnnouncementTime` key exists on any
  engine-internal object. Asserts the variable truly gone, not just
  unused.
```
Add a structural (Python, grep-based) test in `tests/test_navigation_static.py`
that `lastAnnouncementTime` does not appear anywhere in `frontend/navigation.js`.

---

### F3.8 — I8 (muted populates announcedSet) not tested

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §5 I8 and §E9 both claim: "`muted = true` prevents
`onVoiceCb` invocation but does NOT prevent `announcedSet` population."
§6 has no test that mute state is orthogonal to announcedSet population.
**Bug class that could ship:** A subagent reading §4.3 sees the two lines:
```js
announcedSet[nearKey] = true;
announcedSet[farKey] = true;  // D1 suppression
if (!muted && onVoiceCb) onVoiceCb(text);
```
And "refactors" to:
```js
if (!muted && onVoiceCb) {
  announcedSet[nearKey] = true;
  announcedSet[farKey] = true;
  onVoiceCb(text);
}
```
Because "why mark them announced if we didn't announce?" This is a
plausible refactor that subtly breaks I8. The subagent runs all tests
and nothing fails. User then mutes at route-start, drives past two
maneuvers (silently), un-mutes, and **re-hears** both crossed
thresholds as `speechSynthesis.speak` queues them up. Terrible UX —
dangerous too if they fire while the driver is executing a later
maneuver.
**Proposed fix:**
**Test specification:**
```
Test 6.8a — muted populates announcedSet:
  Setup: 2-maneuver route. Call nav.setMuted(true).
  Drive approach that would normally fire near-tier for maneuver 1.
  Assert:
    - onVoice callback NOT invoked (count = 0).
    - internals._getAnnouncedSet() (new test hook) contains
      "1-near" and "1-far" keys.
  Then un-mute via setMuted(false). Drive ONE MORE tick (same
  position).
  Assert: still no onVoice invocation — already-crossed threshold
  must not re-fire.

Test 6.8b — un-mute mid-route does not re-fire:
  Drive past maneuver 1 (near-tier fired, unmuted, 1 prompt).
  setMuted(true). Drive past maneuver 2 (silently populates).
  setMuted(false). Continue driving past the arrival.
  Assert: total onVoice callback count = 1. Not 2. Not 3.
```
Add test-hook: `_getAnnouncedSet: function () { return
Object.assign({}, announcedSet); }` alongside `_getSpeedSamples`.

---

### F3.9 — I7 (next-after-next chain on near-tier only) weakly tested

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §5 I7 "Next-after-next chain is appended on near-tier
only, never on far-tier. Preserves existing behavior." §6.4 asserts the
chain IS appended ("Each near-tier prompt includes the ', then <next>'
chain because maneuvers are within 500m of each other") but does NOT
assert the negative case — that the FAR-tier prompt, when it fires,
does NOT include the chain.
**Bug class that could ship:** The existing code at navigation.js:393-405
has the chain logic nested inside the `isNearTier` branch. Under TTM's
§4.3, the chain is inside the `nearWouldFire` block. A subagent doing a
post-§4.3 refactor ("consolidate the chain logic to avoid duplication
between the two branches") easily hoists the chain to the top of
`checkVoice` and appends it to BOTH far-tier and near-tier text. Every
test except a specific negative assertion passes.

The existing pre-band-aid engine had this invariant implicit; making it
explicit here is cheap insurance since the refactor target is literally
one edit away.
**Proposed fix:**
**Test specification:**
```
Test 6.9 — far-tier prompt does NOT include ", then" chain:
  Setup: 3-maneuver route, maneuvers at 800m, 830m, 860m from start.
  Enter at 1000m, speed 30 m/s.
  Expected: far-tier fires at ~900m using maneuver 1's
    verbal_transition_alert_instruction. Assert the prompt text does
    NOT contain ", then ".
  Then continue driving to 90m. Near-tier fires. Assert prompt text
    DOES contain ", then ".
```

---

### F3.10 — Dead-reckoning + TTM interaction (§E7) not tested

**Severity:** NICE-TO-HAVE
**Claim/gap in spec:** §E7 "Dead-reckoning tick during GPS outage.
`deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap.
`lastSpeed` from the last real GPS tick is used by DR's extrapolation but
`speedMedian()` reads `speedSamples` — these do not update during DR. TTM
during DR uses the last-real-median."
**Bug class that could ship:** A subagent reading §E7 may "fix" the apparent
inconsistency by pushing `lastSpeed` into `speedSamples` during DR ticks.
This is wrong — DR is extrapolation, not observation, and biases
`speedSamples` toward the last-real value indefinitely if GPS stays down
for 30 seconds. Under the current spec, `speedMedian()` during DR returns
the correct last-real-median. The spec asserts this is intended but has
no test.

Additionally: if GPS recovers mid-DR, the first new sample enters
`speedSamples` with the (possibly outdated) previous two samples still
present. If those two are 30 seconds stale, the median is misleading.
The spec doesn't address staleness.
**Proposed fix:** Add note + test:
**Test specification:**
```
Test 6.10 — DR does not pollute speedSamples:
  Setup: Drive 5 ticks at 10 m/s. Confirm speedSamples = [10, 10, 10].
  Stop feeding updateGPS(). Wait (or mock time advance) 10 s to enter DR.
  Trigger a deadReckonTick() (public API or test hook).
  Assert: internals._getSpeedSamples() === [10, 10, 10] — unchanged.
  Assert: checkVoice was called during DR (verify via a spy on onVoice
    or via test hook exposing the last DR invocation).

E7 note to add: "speedSamples are not time-stamped. After a long GPS
gap + DR + recovery, the first new sample enters a buffer of potentially
stale values. Acceptable because median rejects the outlier and the
buffer refreshes over 3 ticks (~3 seconds at 1 Hz)."
```

---

### F3.11 — §6.5 manual regression gate has no GPX-replay automation path

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §6.5 "re-drive the Villa Rita → Costco westerly-detour
route...Ship criteria: ≤ 3 prompts for the rerouted 3-maneuver cluster."
**Bug class that could ship:** The ship gate is a one-shot human test.
If it passes at merge and a subsequent unrelated PR subtly regresses the
prompt count (e.g., a refactor of `distanceToManeuver`), nobody notices
until Cameron drives the route again. The 2026-04-20 nav UX remediation
explicitly flagged this class — green unit tests coinciding with field
disasters.

The `dev/harness/drive-nav.mjs` already exists (per the directory listing)
and knows how to exercise the engine via a Playwright-driven browser. A
recorded GPX of the Villa Rita drive, replayed through drive-nav.mjs
against the TTM-updated engine, is a cheap automated regression for this
exact scenario.
**Proposed fix:** Add §6.5b (optional but recommended) automation path:
**Test specification:**
```
§6.5b — GPX-replay regression harness (recommended, not ship-blocker):
  1. On the §6.5 manual drive, record a GPX track via any phone app
     (Cameron already mentioned owning a Pixel in prior handoffs;
     Android has a dozen GPX-loggers).
  2. Save to dev/harness/fixtures/villa-rita-ttm-regression.gpx.
  3. Extend drive-nav.mjs with a --gpx-file mode that feeds the track
     as updateGPS() calls at 1 Hz.
  4. Assert final prompt count in the onVoice spy ≤ 3.
  5. Wire into frontend-ci.yml as a nightly (not per-PR) job, OR as a
     "nav-critical" job that runs only when frontend/navigation.js is
     touched.

If Cameron declines the GPX recording (field conditions / time), the
spec should at least say explicitly: "§6.5 is a human-only gate. No
automated regression replaces it. A future spec may add GPX-replay
automation if a post-merge field regression occurs."
```

---

### F3.12 — Non-auto costing tests trimmed to "one scenario per costing" — bicycle floor interaction untested

**Severity:** MUST-FIX
**Claim/gap in spec:** §6.1 "Costings: {auto, bicycle, pedestrian} — at
minimum, one maneuver scenario per costing to confirm the per-costing
constants are plumbed."
**Bug class that could ship:** "Plumbing confirmation" tests that one
costing produces some prompts at some speed. They do NOT exercise the
interaction between the per-costing TTM pair and the per-costing distance
floor. Specifically:
1. **Bicycle at 5 m/s** (typical 11 mph): TTM-far fires at `dist = 5 ×
   20 = 100m`. But the bicycle distance floor is 30m. If the cyclist
   enters 35m from the maneuver at 5 m/s (TTM = 7s, less than near's
   3s? no — 7s > 3s; dist = 35m > 30m floor), neither near condition is
   met. Far condition: TTM = 7s, threshold 20s. Is `7 ≤ 20`? Yes,
   far fires. But in the §6.4 Villa Rita scenario the cluster-test
   costing is assumed `auto`. No cell checks bicycle+floor interaction.
2. **Pedestrian at 1.5 m/s** (walking): TTM denominator = MIN_SPEED_FLOOR
   (1.0), ttm = dist. Near threshold 2s → fires at 2m. Floor = 15m →
   fires at 15m. The floor wins. Nobody tests this; the TTM math for
   pedestrians is effectively unused except as a safety fallback.
3. **Auto at highway speed + bicycle floor comparison:** no cross-costing
   comparison test. If VOICE_TTM.bicycle is accidentally set to the auto
   values in a merge conflict, no test catches it until field-tested by
   a cyclist (low probability on this beta audience).
**Proposed fix:** Expand the matrix:
**Test specification:**
```
Add §6.1b — per-costing floor interaction:
  For each costing in {auto, bicycle, pedestrian}:
    Test at speed = VOICE_TTM[costing][0] × VOICE_DISTANCE_FLOOR[costing] /
      VOICE_TTM[costing][1]
    (the speed where far-by-TTM and near-by-floor coincide — the
     interesting boundary).
    Assert exactly 2 prompts: far-tier when TTM crosses, near-tier
    when floor crosses.

Add §6.1c — cross-costing constant mismatch regression:
  Assert VOICE_TTM.bicycle !== VOICE_TTM.auto (distinct array
  identity AND distinct values, to catch accidental shared references
  and accidental value copies).
  Assert VOICE_TTM.pedestrian[0] < VOICE_TTM.auto[0] (pedestrian is
  slower than auto).

Add named test cells covering bicycle low-speed (5 m/s, 35m entry) and
pedestrian walking (1.5 m/s, 20m entry).
```

---

### F3.13 — Test hooks migration: spec says "consumer tests migrate" but grep shows other references

**Severity:** SHOULD-FIX
**Claim/gap in spec:** §6.6 "Update the band-aid regression test...by
deleting it in this PR. Any other cooldown / speed-gate consumers migrate
to the new TTM hooks."
**Bug class that could ship:** I grep'd the repo. `VOICE_THRESHOLDS` +
`VOICE_COOLDOWN` + `VOICE_SPEED_GATE` + `VOICE_NEAR_ANNOUNCE_DISTANCE`
+ `lastAnnouncementTime` appear in:
- frontend/navigation.js (source, gets edited — fine)
- frontend/tests/engine/navigation.test.mjs (4 refs — flagged in F3.3)
- dev/testing-pitfalls.md (documentation, may need update)
- dev/implementation-log.md (historical — should not be edited)
- dev/bug-hunts/2026-04-21-nav-uxb-*.md (5 files, bug-hunt artifacts —
  historical, do not edit)
- docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md (plan doc —
  historical, should not be edited)
- docs/superpowers/specs/2026-04-14-navigation-bug-fixes-design.md (old
  spec — historical)

The **TEST file** is the only edit target beyond navigation.js itself,
and F3.3 already addresses it. But the spec does not explicitly enumerate
the grep targets, so a conservative subagent may edit historical
bug-hunt docs or the old design doc "for consistency," polluting the
audit trail.
**Proposed fix:**
**Test specification:**
```
§6.6 addition:
  "The ONLY files to edit in this PR besides navigation.js are:
    - frontend/tests/engine/navigation.test.mjs (delete band-aid test,
      rename 'applyReroute clears' test per F3.3, add new TTM tests).
  Do NOT edit:
    - dev/implementation-log.md — historical, append-only, new entry
      at top is fine.
    - dev/bug-hunts/* — bug-hunt artifacts; historical.
    - dev/testing-pitfalls.md — may add NEW entry if a new pitfall
      emerges but do not edit references to VOICE_THRESHOLDS.
    - docs/superpowers/specs/2026-04-14-* — historical spec.
    - docs/superpowers/plans/2026-04-21-nav-uxb-remediation.md — historical plan."

Add a plan Task verification: grep for VOICE_THRESHOLDS post-merge.
Expected: zero results under frontend/, zero under tests/. Non-zero
under dev/ + docs/* (historical refs) is fine.
```

---

### F3.14 — Test fixtures use full Valhalla maneuver shape; TTM tests may skip required fields

**Severity:** NICE-TO-HAVE
**Claim/gap in spec:** §6 doesn't mention what fields a test maneuver
needs. The existing `fixtureRouteWithTwoTurns()` at
test_runner.mjs:50 has: `type`, `instruction`,
`verbal_transition_alert_instruction`, `verbal_pre_transition_instruction`,
`begin_shape_index`, `end_shape_index`.
**Bug class that could ship:** The §6.4 Villa Rita synthetic says
"maneuvers spaced 30m apart." If the author hand-rolls a minimal maneuver
object (only `instruction` + `begin_shape_index`), the D1 suppression
chain logic at §4.3 line 200 `distanceToManeuver({segmentIndex:
m.begin_shape_index, t: 0}, afterIdx)` works; but the prompt-text
assertion "Each prompt uses the `verbal_pre_transition_instruction` text"
fails silently because the field is missing. A subagent writing the test
may skip the field and use the fallback `m.instruction`, then "fix" the
assertion to accept either text — masking the bug.
**Proposed fix:**
**Test specification:**
```
§6.4 addition:
  "Use fixtureRouteWithTwoTurns() as the basis for the 3-maneuver Villa
  Rita synthetic. Extend with an `extraManeuvers` parameter that appends
  additional maneuvers with FULL Valhalla field shape:
    { type, instruction, verbal_transition_alert_instruction,
      verbal_pre_transition_instruction, begin_shape_index,
      end_shape_index }
  All four text fields MUST be distinct so assertions can discriminate
  which one was used (e.g., 'FAR_ALERT_1', 'PRE_TRANSIT_1', 'INSTR_1')."

Additionally: the fixture file should live under
  frontend/tests/engine/fixtures/ssouter than inline in test_runner.mjs
  (per the existing NOAA fixture pattern) so the Valhalla-captured
  villa-rita-detour.json from F3.5 has a home.
```

---

## Cross-cutting observations

1. **The §6 matrix is marketing-shaped, not engineering-shaped.** "4 × 4 ×
   3 = 48 cells; trim to ~12 representative cells" is vague enough that
   any subagent can ship 12 cells and claim conformance, but those 12 may
   leave I5 / I7 / I8 uncovered. The invariant→cell mapping below should
   be explicit in §6.1:

   | Invariant | Required cell | Notes |
   |-----------|---------------|-------|
   | I1 | speed=10, entry=500, auto | 2 prompts |
   | I2 | speed=10, entry=40, auto | 1 prompt (D1) |
   | I3 | speed=0, entry=80, auto | 0 prompts |
   | I4 | speed=0, entry=40, auto | 1 prompt (floor) |
   | I5 | F3.1 (outlier-in-3) | MUST add |
   | I6 | §6.3 reroute test | OK |
   | I7 | F3.9 (far vs near chain) | MUST add |
   | I8 | F3.8 (muted populates) | MUST add |

2. **Test-hook surface expansion.** §4.6's `_getSpeedSamples` is good but
   leaves `announcedSet` inspection to the integration-test path. Adding
   `_getAnnouncedSet` is cheap and unlocks F3.8 and F3.3.

3. **Two spec-level decisions disguised as "testing details."** F3.4
   (fake-timer) and F3.6 (non-auto costing) are framed as test coverage
   but are real design ambiguities. Defer them to spec-v2 resolution,
   not plan-task guesswork.

4. **The §6.5 ship gate is load-bearing and Cameron-dependent.** If
   Cameron is the only field-test operator and travel or life schedule
   delays the drive, merge is blocked. F3.11's GPX-replay path gives an
   emergency unblock with acceptable risk (recorded-once ≠ live, but
   beats "wait indefinitely for Cameron's calendar").

5. **No performance bound.** `speedSamples.slice().sort()` on every
   `checkVoice` call is O(3 log 3) which is free, but if someone later
   tunes `SPEED_WINDOW_SIZE = 15` for smoother behavior, each tick does
   O(15 log 15) inside the 1 Hz tick loop. Not a spec-v1 problem but
   worth a note in §E that `SPEED_WINDOW_SIZE` is a correctness knob,
   not a performance knob — raising it changes outlier-rejection depth,
   not smoothness.

6. **Coverage of E1-E9 in the test matrix.** E1 (warmup), E2 (GPS never
   arrives), E5 (stopped at light at turn), E6 (stopped at light beyond
   floor) all have natural matrix cells. E3 (decelerating driver),
   E4 (accelerating driver), E7 (DR), E8 (empty text), E9 (mute toggle
   mid-maneuver) do not. E9 is addressed by F3.8; E7 by F3.10; E3/E4/E8
   are left unchecked. NG2 defers E3 formally, so it's fine. E4 and E8
   are untested and undocumented as intentionally-untested.

---

## Summary of required spec-v2 edits

- **§6.1:** specify `simulateApproach` contract (F3.2); add invariant→cell
  mapping table; add bicycle/pedestrian floor-interaction cells (F3.12);
  add unknown-costing fallback cells (F3.6).
- **§6.2:** add two-outlier and warmup-outlier cases (F3.1).
- **§6.3:** rename existing test, add speedSamples assertion, audit
  coord (F3.3).
- **§6.4:** capture real Valhalla response or loosen success criterion
  (F3.5); use full-shape maneuver fixture (F3.14).
- **§6.5:** document GPX-replay path as optional automation (F3.11).
- **§6.6:** enumerate which files to edit and which are off-limits (F3.13).
- **§6.7 (NEW):** cooldown-removal regression test (F3.7).
- **§6.8 (NEW):** muted populates announcedSet (F3.8).
- **§6.9 (NEW):** far-tier does not include chain (F3.9).
- **§6.10 (NEW):** DR does not pollute speedSamples (F3.10).
- **§4.6:** add `_getAnnouncedSet` test hook.
- **§9:** explicitly declare fake-timer infra OUT OF SCOPE (F3.4).
- **§E10 (NEW):** unknown-costing fallback documented (F3.6).
