---
round: 6
angle: Codex cross-validation
reviewer: codex v0.118.0
date: 2026-04-20
agent: alder
---

# Round 6 — Codex cross-validation

## MUST-FIX

### F6.1 — The spec’s route-start guarantees do not hold on this engine’s actual `start()` path

**Severity:** MUST-FIX

**Quoted spec claim:** “**G2.** Exactly 1 voice prompt per maneuver when the driver enters already inside the near-tier condition” and “**G4.** Near-tier prompt fires when the driver is stationary *at* the next maneuver.”

**Reality / impact:** The live engine does not run the TTM pipeline on `start()`. In [frontend/navigation.js](/home/administrator/Code/geographica/frontend/navigation.js:758), `start()` snaps, stores `lastGPS`, sets `state`, and immediately `emitUpdate(buildState(...))`, but it does **not**:
- set `currentManeuverIdx` from the snap,
- seed `speedSamples`,
- call `checkVoice(snap)`.

That means the spec’s route-start and “already inside near-tier” scenarios are not true on the codepath users actually hit when starting navigation on-route. If the user starts 20-40m before a turn, they get no prompt on activation. If GPS then keeps reporting the same lat/lon, [updateGPS](/home/administrator/Code/geographica/frontend/navigation.js:802) dedups unchanged positions and still does not call `tick()`, so the prompt can remain suppressed until the vehicle moves.

There is a second-order correctness issue too: `buildState()` reads `currentManeuverIdx`, but `start()` leaves it at the reset default `0`, so a mid-route start can render the wrong `nextManeuver` until the first movement tick.

**Proposed fix:** The spec needs an explicit startup-initialization step, not just a `tick()` rewrite. On the on-route branch of `start()`:
- set `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`,
- seed the speed window from `savedGPS.speed`,
- decide whether `checkVoice(snap)` is allowed on start or explicitly deferred.

If immediate start-time voice is desired, say so and update `nav-ui.js` assumptions too. If not, narrow G2/G4 so they apply only after the first post-start GPS tick.

---

### F6.2 — “No nav-ui changes” becomes false if start-time voice is allowed

**Severity:** MUST-FIX

**Quoted spec claim:** “**NG3.** Changes to `frontend/nav-ui.js`’s voice pipeline. The engine-side `onVoiceCb(text)` contract is preserved exactly” and “**G9.** Mute-state interaction unchanged.”

**Reality / impact:** The current UI wiring assumes `nav.start()` is voice-silent. In [frontend/nav-ui.js](/home/administrator/Code/geographica/frontend/nav-ui.js:154), the order is:

1. `nav.onVoice(onVoice)`
2. `nav.start(routeData)`
3. `nav.setMuted(muted)`
4. `WakeLock.acquire()`
5. `primeSpeech()`

If the TTM spec is implemented literally enough to satisfy G2/G4 on start, the first prompt can fire **before** mute sync and **before** speech priming. That creates two regressions the spec currently says do not exist:

- A muted user can still hear the first prompt, because engine `muted` defaults false until [line 161](/home/administrator/Code/geographica/frontend/nav-ui.js:161).
- The first utterance can happen before the UI’s speech warm-up path, which the file explicitly treats as ordering-sensitive.

This is not theoretical; it is a direct consequence of fixing F6.1 without updating the UI contract.

**Proposed fix:** The spec must choose one of these and say so explicitly:
- Keep `start()` voice-silent and scope G2/G4 to post-start GPS ticks only.
- Or allow start-time voice, but then `nav-ui.js` is in scope: move `nav.setMuted(muted)` before `nav.start(routeData)`, and re-evaluate whether `primeSpeech()` / wake-lock ordering must move too.

Right now the spec promises both “route-start prompt works” and “no nav-ui changes,” but this codebase cannot satisfy both simultaneously.

---

### F6.3 — The synthetic “3-maneuver cluster → 3 prompts” test is off by one against actual engine maneuver semantics

**Severity:** MUST-FIX

**Quoted spec claim:** “**§6.4 Dense-cluster (Villa Rita synthetic) test:** Synthesize a **3-maneuver route** with maneuvers spaced 30m apart… Assert exactly **3 voice prompts** fired.”

**Reality / impact:** This engine voices the **upcoming** maneuver at `nextIdx = currentManeuverIdx + 1`; it does not voice the maneuver you are already on. The existing fixture in [frontend/tests/engine/test_runner.mjs](/home/administrator/Code/geographica/frontend/tests/engine/test_runner.mjs:48) shows the convention clearly: a “3-maneuver route” is actually “2 turns + arrival,” and the first spoken turn is maneuver index `1`, not `0`.

So a literal “3 maneuvers total” synthetic route cannot produce “3 spoken maneuver prompts” under current semantics unless you also change initialization semantics. With the current engine model, a “3 prompts in a close cluster” scenario needs either:
- 4 maneuvers total (lead/current + 3 upcoming spoken maneuvers), or
- an explicit change in how `currentManeuverIdx` is initialized for synthetic tests.

If this is left ambiguous, an implementer can write a passing synthetic that does not correspond to live engine behavior, or a failing one that appears to disprove the spec even though the geometry is wrong.

**Proposed fix:** Rewrite §6.4 in engine-native terms:
- either “3 **upcoming spoken maneuvers** after the current leg,”
- or “4 maneuvers total, yielding 3 spoken prompts.”

Also specify whether arrival is part of the count. The current wording mixes product-language “maneuver count” with engine-language “next maneuver index” and will mislead test authors.

---

### F6.4 — G7 overclaims determinism; this engine still depends on wall-clock scheduling, not just route + GPS values

**Severity:** MUST-FIX

**Quoted spec claim:** “**G7.** Behavior is deterministic: identical `(route, GPS stream)` inputs produce identical announcement counts and timing. No hidden cooldown or randomness.”

**Reality / impact:** In this codebase, voice timing is not determined solely by route shape and GPS sample values. It also depends on real clock behavior:

- `tick()` uses `Date.now()` repeatedly in [frontend/navigation.js](/home/administrator/Code/geographica/frontend/navigation.js:549).
- stale-GPS voice can be generated by the 1 Hz interval in [startStaleChecker()](/home/administrator/Code/geographica/frontend/navigation.js:706).
- `updateGPS()` ignores the incoming `gpsData.timestamp` field and stamps `lastGPSTime = Date.now()` itself at [line 816](/home/administrator/Code/geographica/frontend/navigation.js:816).

So the same coordinate/speed sequence delivered with different inter-arrival timing can produce different results:
- one run may enter dead reckoning and fire voice,
- another may not,
- reroute timeout behavior also changes with wall-clock delay, not just sample content.

That does not make the design invalid, but the invariant as written is false for the real engine.

**Proposed fix:** Narrow G7 to something the implementation can actually guarantee, for example:
- “Deterministic for identical route, GPS samples, and timer schedule,” or
- “Deterministic on the direct `tick()` path; stale-GPS / DR paths remain clock-dependent.”

Also make the test plan reflect that scope. Otherwise the spec is promising a property the engine architecture does not have.

---

## SHOULD-FIX

### F6.5 — Prompt counts in the spec are callback counts, not necessarily user-heard prompts

**Severity:** SHOULD-FIX

**Quoted spec claim:** “Villa Rita post-reroute 3-maneuver cluster: **3 prompts total**” and “Pass: **≤ 3 prompts** for the rerouted 3-maneuver cluster.”

**Reality / impact:** In the actual UI, each voice event cancels whatever is currently speaking before starting the new utterance. See [frontend/nav-ui.js](/home/administrator/Code/geographica/frontend/nav-ui.js:494):

```js
speechSynthesis.cancel();
speechSynthesis.speak(utterance);
```

That means the spec’s prompt counts are counts of `onVoiceCb` invocations, not necessarily counts of complete audible prompts. In a dense cluster, “3 callbacks” can still sound like “the first phrase got chopped off, then another one interrupted it.” That is a materially different user outcome from the safety claim the spec is making.

Rounds 1–5 focused on when the engine fires. The missing cross-validation point is that the UI currently treats prompts as preemptive, not queued.

**Proposed fix:** In §6.5, define the field gate in audible terms, not just callback-count terms. At minimum capture:
- callback count,
- whether any prompt was canceled by a later one,
- subjective audibility/intelligibility.

If you want to keep NG5 as-is, then at least state explicitly that the “3 prompts” headline means “3 engine callbacks,” not “3 fully spoken utterances.”

---

### F6.6 — Mid-route start correctness needs to be named as a precondition or tested explicitly

**Severity:** SHOULD-FIX

**Quoted spec claim:** “TTM is a pure in-engine change. External contract surfaces are unchanged.”

**Reality / impact:** The spec repeatedly reasons about “route-start into a close maneuver” and “post-reroute into a close maneuver,” but this engine also supports starting while already on-route or partway through a route. On that path, [start()](/home/administrator/Code/geographica/frontend/navigation.js:758) currently emits UI state without reconciling `currentManeuverIdx` to the snap. That is not just a voice issue; it is a general navigation-state issue, and TTM makes it more visible because voice timing now depends on a correctly identified “next maneuver.”

If the spec is intentionally not fixing mid-route start semantics, it needs to say that. Otherwise implementers will assume the existing startup behavior is already valid and only patch `checkVoice()`.

**Proposed fix:** Add one explicit statement to the spec:
- either “TTM assumes `start()` is corrected to initialize maneuver state from the snap,”
- or “mid-route start remains out of scope; TTM correctness is guaranteed only after the first movement tick.”

A single engine test for “start while already snapped after maneuver 0” would close this gap cleanly.

---
