---
round: 5
angle: Product, UX, and field-context framing
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-20
agent: alder
---

# Round 5 adversarial review — Nav voice TTM spec, product / UX / field-context lens

Reviewing `docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md` (v1).

The 2026-04-20 Villa Rita → Costco field run produced 9 voice prompts in
~200 ft of driving under the band-aid thresholds `[400m, 50m]`. Unit tests
were green throughout. This spec is Cameron's response: swap distance for
time, add D1 suppression, delete the band-aid. The thesis is plausible. The
question for this round is whether the spec actually buys the driver
experience Cameron thinks he's buying, or whether the "3 prompts from 9"
number on the tin is an accounting artifact that doesn't survive contact
with a beta tester's real route.

I traced the algorithm by hand against the scenarios §1 and §6.4 claim,
checked how Valhalla's voice text interacts with the engine's TTM clock,
and pressure-tested the goals against Geographica's actual audience (AREDN
mesh, SAR, trail-driving, urban Phoenix, highway). I also spent time on
the question Cameron specifically flagged in the task: is [30s, 3s]
*actually* tighter than [400m, 50m] in the regime field-testers said was
"too far out"? The answer is mixed and worth a finding.

Findings below are ordered severity-first. I was asked for 5–10; I landed
on 9.

---

### F5.1 — "Villa Rita 9 → 3" is accounting, not algorithm — the math only holds under a specific tick timing

**Severity:** MUST-FIX
**Framing question:** Does the spec's headline safety claim verify against
the algorithm as written?

**Current spec position:** §1 and §6.4 both advertise "3 prompts for the
3-maneuver Villa Rita cluster, down from 9." §6.4 specifies the test
scenario: 3 maneuvers 30m apart, entry 40m before M1, 10 m/s, auto
costing.

**Challenge:** I traced the scenario tick-by-tick against §4.3's
`checkVoice`:

- **Tick 0 (t=0s, 40m from M1, speed=10 m/s):** `distToNext = 40`,
  `ttm = 4s`, `speedMedian()` needs ≥1 sample to return 10 (warmup:
  §4.2 `speedMedian` returns `MIN_SPEED_FLOOR = 1.0` when
  `speedSamples.length === 0`, but since `pushSpeedSample` fires
  *before* `checkVoice` in the tick, the buffer has 1 element by the
  time `checkVoice` runs — OK). Near check: `4 <= 3` FALSE, but
  `40 <= 50` floor TRUE → near fires for M1. D1 marks far-M1
  consumed. Count = 1.
- **Tick advances `currentManeuverIdx` how?** The spec inherits
  `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`
  from navigation.js:573 (I verified this in the source). It updates
  when the snapped segment crosses a maneuver's shape boundary. For
  M1→M2 30m apart at 10 m/s, that's ~3 seconds at 1 Hz GPS — so
  *tick 3* is when M2 becomes the next maneuver.
- **Ticks 1, 2 (t=1s, 2s, between M1 and M2 boundary):** Still M1 as
  next. But `announcedSet["1-near"]` and `announcedSet["1-far"]` are
  both set. No fire. ✓
- **Tick 3 (t=3s, just past M1, M2 is now next, ~30m ahead, 10 m/s):**
  `distToNext = 30`, `ttm = 3.0s`. Near: `3.0 <= 3` TRUE → near
  fires M2. Count = 2.
- **Tick 6 (t=6s, past M2, M3 next, ~30m ahead):** same → near fires
  M3. Count = 3. ✓

So the claim holds **for this exact synthetic scenario**. But the
scenario is brittle on several dimensions:

1. **Spacing sensitivity.** If maneuvers are 35m apart instead of 30m,
   `ttm = 3.5s` at 10 m/s. Near: `3.5 <= 3` FALSE, `35 <= 50` floor
   TRUE → still fires near. Fine. If they're 55m apart: `ttm = 5.5s`,
   `55 <= 50` floor FALSE, `ttm <= 3` FALSE → near does NOT fire on
   first tick it's eligible. Far checks: `5.5 <= 30` TRUE → **far
   fires**. Then at ~30m, near fires. That's 2 prompts for M2, not
   1. So a 3-maneuver cluster with 55m spacing yields **5 prompts,
   not 3**. Villa Rita-style real roads don't come in exactly 30m
   spacings; any cluster with spacing between ~50m and ~300m defeats
   D1 and produces the 2-per-maneuver cadence D1 was supposed to
   suppress.
2. **Entry-distance sensitivity.** §6.4 says "entry 40m before M1" →
   inside the 50m floor → D1 trips cleanly. If the driver enters at
   80m (outside the floor, inside far): tick 0 fires far. Tick ~5
   fires near. M2, M3 each get 2 prompts → **7 prompts total**. The
   "entry already inside near" assumption is load-bearing for the
   G2 invariant, but the field scenario that *caused* this spec was
   a **reroute**, and the reroute could place the user anywhere
   relative to the first maneuver of the new route.
3. **Ticks vs fence-post.** At exactly 30m spacing and exactly 10 m/s,
   `ttm = 3.0s`. The comparison is `ttm <= 3` — equality passes. At
   11 m/s, spacing 30m → `ttm = 2.73s` → still passes. At 9 m/s,
   spacing 30m → `ttm = 3.33s` → FAILS the near gate, but
   `30 <= 50` floor passes. So auto's 50m floor masks the speed
   variance in this scenario — but the floor is exactly the thing
   that makes the scenario's D1 behavior work, and the floor is
   costing-specific. For `bicycle` (floor = 30m), the same 30m
   spacing is on the knife-edge of the floor.

**Impact:** The §1 "3 prompts" number is real but load-bearing on the
exact §6.4 scenario. The field observation that motivated this work
(9 prompts at Villa Rita) was **not** 3 maneuvers at exactly 30m and
10 m/s — it was whatever the real streets were, which we don't know
because there's no GPS log attached to the field report. The spec
should either (a) explicitly scope the G2 claim to "entry inside
near-tier" and note that cluster-spacing between the floor and the
far-threshold-at-10-m/s produces 2-per-maneuver (same as old
system), or (b) introduce a real-route regression test whose
geometry is extracted from a reproduced Villa Rita drive.

**Recommended resolution:** Downgrade §1's "Villa Rita cluster: 3
prompts total" to "entering the cluster already inside near-tier
(e.g., post-reroute into a close first maneuver): 1 prompt per
maneuver via D1 suppression. Entering outside near (e.g., normal
approach to the cluster): 2 prompts per maneuver on the first,
potentially 1 on subsequent if the inter-maneuver distance is
inside the floor." Then add an §6.4b test that captures the
"outside-near entry into a tight cluster" case and asserts its
expected count — 3 maneuvers, 60m spacing, 80m entry, 10 m/s — I
estimate 5 prompts. Ship if that number is acceptable; re-design if
not. Do not let §1 keep the "3 prompts" headline if it's only true
in the hand-picked geometry of §6.4.

---

### F5.2 — [30s, 3s] is LARGER than [400m, 50m] above 13 m/s; band-aid regression for highway users

**Severity:** MUST-FIX
**Framing question:** Cameron's field testers said "current bounds are too
far out." Does the new system actually tighten them, or only in the
regimes they were already tight?

**Current spec position:** §1 frames [30s, 3s] as the response to field
feedback. At city speed (10 m/s), `30s × 10 = 300m` — tighter than the
400m band-aid. ✓

**Challenge:** At highway speed (30 m/s), `30s × 30 = 900m`. The old
band-aid far-tier was 400m, fixed. So at highway speed, TTM fires far
**more than twice as early in distance terms** than the band-aid did.
Set the crossover point: `30s × v = 400m → v = 13.3 m/s ≈ 30 mph`.
Above 30 mph, TTM's far-tier is FURTHER from the maneuver than the
band-aid's far-tier.

This is the opposite of what the field testers asked for. The
band-aid's 400m was derived from "the 800m original was too far"
feedback; the TTM 30s was derived from "30 seconds feels like the
right advance notice" intuition. These two derivations don't agree in
the regime where Cameron's field testers actually complained (city
surface streets at 22–30 mph, where TTM is tighter) vs. the regime
where the complaint was *never* voiced (highway, where TTM is looser
than the band-aid).

Two possible readings:

- A) The field testers' "too far out" complaint was specifically about
  low-speed situations, and high-speed 900m advance notice is
  actually desirable and was never the problem. This is the charitable
  read and is probably what the spec author intended.
- B) The band-aid's 400m was calibrated against the aggregate driver
  intuition across all speeds, and doubling it at highway will read
  as "the nav got chatty again" — a regression.

The spec doesn't distinguish. §1's sentence "matches field-tester
expectation ('current bounds are too far out')" overclaims if B is
right, and is fine if A is right — but the spec has no evidence for
either. The 2026-04-20 handoff explicitly says the Villa Rita scenario
was a **rerouted surface-street cluster**, not a highway — so there is
literally zero highway field evidence for 30s = right.

**Impact:** Shipping without at least one highway beta-test re-drive
risks a second "nav got chatty" complaint, this time at speed, where
9 prompts in 200 ft becomes 5–6 prompts over a mile of freeway — less
obviously dangerous but equally annoying, and harder to catch in post
hoc field reports because highway complaints rarely include
per-prompt counts. The §6.5 ship gate only re-tests Villa Rita.

**Recommended resolution:** Add an §6.5b highway ship-gate: a 10–15
mile stretch of rural highway (I-17 north of Phoenix fits) at a
target speed of 25–30 m/s, count the prompts per maneuver, confirm
driver self-report that the cadence is "about right" or "too chatty."
If too chatty, the fix is `auto: [20s, 3s]` — drops the crossover to
`20s × v = 400m → v = 20 m/s ≈ 45 mph`, which puts most interstate
driving at the-same-or-tighter advance notice as the band-aid.

Also tighten the §1 language: "At highway speed (30 m/s), far fires
at 900m; at city speed (10 m/s), at 300m. The former is genuinely
useful advance notice at interstate speeds; the latter is tighter
than the 400m band-aid. Highway cadence has **not** been field-
validated at time of spec authorship — §6.5b closes this gap."

---

### F5.3 — D1 option-B may swap information-overload for information-STARVATION on reroute

**Severity:** SHOULD-FIX
**Framing question:** The brainstorm rejected option-C (compound prompts)
for information-overload. Is option-B vulnerable to the opposite
failure mode — the driver never hearing "hey, the route has changed"?

**Current spec position:** §4.3 and G2 specify that when the driver
enters the near-tier condition directly (post-reroute to a close
maneuver), the near-tier fires with
`verbal_pre_transition_instruction` (e.g., "Turn left onto Mulberry,
then right onto Cactus"). No far-tier advance notice is spoken.

**Challenge:** Consider the driver's mental model at the moment of
reroute:

1. Driver missed a turn 30 seconds ago.
2. Engine detected off-route and issued a reroute request.
3. Reroute arrives. `applyReroute()` clears `announcedSet` and
   `speedSamples`. Driver is at, say, 40m from the new M1.
4. Next tick fires near-tier for M1: "Turn left onto Mulberry, then
   right onto Cactus."

From the driver's POV, the first thing they hear after the silent
reroute is a *near-term* instruction. They may not have heard the
"rerouting…" announcement (depends on upstream `nav-ui.js` behavior)
or it may have been drowned out. They now need to:

- Recognize this is a new route, not the old one
- Parse the street names (may be unfamiliar — they're in reroute
  territory)
- Execute the turn

Compare the band-aid behavior: far-tier fires first ("In 400m, turn
left onto Mulberry"), giving the driver a framing cue
(advance notice = new route context) before the commit instruction.
D1 removes that cue in exactly the scenarios where it's most needed:
post-reroute, driver is confused, street names are unfamiliar.

This is not a hypothetical. The 2026-04-20 Villa Rita field
observation was a **reroute scenario** — the whole problem exists
because reroute-into-cluster is where TTM behavior matters most.
Shipping D1 without acknowledging this tradeoff means we've fixed
information-overload and potentially created information-starvation
in the same failure mode.

**Possible mitigations (any one of these, or a combination):**

- Append a short reroute tag to the first near-tier prompt after an
  `applyReroute()` call: "New route. Turn left onto Mulberry, then
  right onto Cactus." Requires adding a "first-after-reroute" flag
  to engine state; the flag is cleared on first near-fire.
- Preserve far-tier fire for the **first** maneuver after a reroute
  even when D1 would suppress, on the theory that the driver's need
  for route-change framing outweighs information-overload for one
  prompt.
- Accept the tradeoff explicitly in the spec and document it as a
  known UX wart; plan a v2 iteration if field testing flags it.

**Recommended resolution:** At minimum, spec should name this
tradeoff explicitly in §1 ("D1 trades advance-notice framing for
count reduction — the reroute-into-cluster scenario loses the 'new
route is starting' audio cue"). Better: pick mitigation 1 (reroute
tag prefix) — it's a 10-line diff in `applyReroute` + `checkVoice`,
adds the framing cue only where it's needed, does not increase
count. Add to §6.4 a test that exercises the reroute path and
asserts the first near-prompt after reroute includes the tag.

---

### F5.4 — Spec uses meters; Valhalla's verbal text uses user-configured units → driver-confusing text/timing mismatch

**Severity:** SHOULD-FIX
**Framing question:** Does the text the driver hears agree with the
distance the engine is using to decide *when* to speak?

**Current spec position:** §4.3 uses meters throughout for the TTM
distance calculations. The voice text comes verbatim from Valhalla's
`verbal_transition_alert_instruction` and
`verbal_pre_transition_instruction` fields.

**Challenge:** I verified in `frontend/nav-ui.js:529` and
`frontend/app.js:2084` that the Valhalla route request includes
`directions_options: { units: useImperial ? 'miles' : 'kilometers' }`.
For US users (the primary Geographica audience — AREDN, SAR, western
US NAIP imagery focus), `useImperial` is typically true. Valhalla
then bakes the units into its verbal text:
- `verbal_transition_alert_instruction`: "In 1 mile, turn left onto
  Mulberry" or "In 500 feet, turn left" — at Valhalla-chosen
  distances.
- `verbal_pre_transition_instruction`: "Turn left onto Mulberry" (no
  distance, consistently).

Valhalla's alert-instruction distance is **not** the same as TTM's
far-tier threshold. Valhalla picks from a fixed ladder (1/4 mile,
1/2 mile, 1 mile, etc.) based on its own heuristics. The TTM engine
fires the alert instruction when `ttm <= 30s` — which is 900m at
30 m/s, or roughly 0.56 miles.

Concrete driver experience at highway speed:
- At 900m-from-maneuver, TTM fires. Text emitted is Valhalla's
  canned "In half a mile, turn left onto Mulberry" (say, since 900m
  ≈ 0.56 mi, Valhalla probably picked 0.5 mi alert).
- Actual distance at fire time: 900m = 0.56 mi. Text says 0.5 mi.
  Driver half-notices the discrepancy but it's within tolerance.

Concrete driver experience at city speed with short spacing:
- 3 maneuvers, 60m spacing, 80m entry, 10 m/s. Far fires at
  tick 0 for M1. `distToNext = 80m = 263 ft`. Valhalla's canned
  text for this distance is probably "In 250 feet, turn left onto
  Mulberry" or similar.
- Tick ~5, near fires M1. Driver hears "Turn left onto Mulberry."
- Tick ~6, M2 becomes next. TTM = 6s from 60m. `ttm <= 30s` TRUE
  → far fires M2. `distToNext = 60m = 197 ft`. Valhalla's text:
  "In 200 feet, turn right onto Cactus."
- Tick ~12, near fires M2 at floor.

In this scenario the driver hears three "In N feet" prompts in
quick succession, each with a Valhalla-picked distance that doesn't
match the TTM engine's mental model. The text and the clock drift
apart.

This is not a bug the existing system avoided — the legacy
`[800, 200, 50]` tiers had the same problem, and the band-aid's
[400, 50] had it too. But §1 of the spec claims "genuinely useful
advance notice at interstate speeds" without noting that Valhalla's
verbal text may read "In 1 mile" when TTM fires 0.56 mi out, or "In
250 feet" when TTM fires 80m out, etc. The driver's trust in the
system is calibrated on whether the text matches their intuitive
sense of distance — a mismatch here is a credibility cost even if
not a safety cost.

**Impact:** Minor UX papercuts at every fire, accumulating into
driver distrust. Not severe, but worth naming so the team doesn't
claim "TTM produces accurate distance-to-maneuver text" — it
explicitly doesn't.

**Recommended resolution:** Add to §5 or §7 a new edge case E10:
"Verbal text distances (Valhalla-chosen) and TTM fire timing
(seconds-normalized) are not synchronized. Valhalla's `In N feet/
miles` comes from its own distance-ladder heuristic; the engine
fires at `ttm <= 30s` regardless of which rung Valhalla chose. Text
may say `In 1 mile` when the engine fired at 900m (= 0.56 mi) or
`In 500 feet` when the engine fired at 150m (= 492 ft). This is
cosmetic drift and matches legacy behavior; no fix planned. Future
spec could override Valhalla's text with engine-computed
distance strings, but that breaks the 'Valhalla text is canonical'
boundary."

---

### F5.5 — NG1 highway-exit deferral: the failure mode is "20 minutes off-route," not a UX papercut

**Severity:** SHOULD-FIX
**Framing question:** Is the cost of missing a highway exit actually
acceptable to defer to a "future spec if beta testers complain"?

**Current spec position:** NG1: "Highway-exit 3-tier announcements
(Google/Apple-style 'in 2 miles / in half a mile / now'). Deferred.
If beta-testers complain about missed exits on highway trips, a
future spec adds a per-maneuver-type tier override for `ramp /
exit_left / exit_right`. Geographica's AREDN / SAR / trail-driving
audience is surface-street-heavy; this is not the v1 priority."

**Challenge:** Two things make this deferral more costly than the
framing admits:

1. **The cost asymmetry is severe.** Missing a surface-street turn
   costs ~30 seconds of rerouting. Missing a highway exit on
   interstate costs **up to 20+ minutes to the next exit** in
   rural western US (I-17 through Black Canyon has exits ~10 mi
   apart; US-93 north of Wickenburg has 20+ mi gaps). For SAR
   scenarios, that's potentially life-critical delay. The
   "surface-street-heavy" audience claim understates the
   consequence of the rare-but-severe highway case.
2. **The feedback loop is slow.** NG1 says "if beta-testers
   complain." But a beta tester who misses an exit and gets
   rerouted doesn't necessarily report it as a nav bug — they
   report it as "my phone's nav is bad." The signal that makes it
   back to Cameron is muted, delayed, or absent. By contrast, the
   Villa Rita 9-prompt scenario was egregious enough to be
   self-reporting. Highway-exit-miss failure is **quieter and
   more dangerous** than surface-street-overprompt failure.

The 30s far threshold at 30 m/s = 900m = 0.56 mi. US interstate
signage calibration is 2 mi / 1 mi / 0.5 mi / 0.25 mi / exit. TTM
only fires inside 0.56 mi, so the driver gets **one** advance
notice (at 0.56 mi) before the near-tier at 90m (= 300 ft), which
is too close to react to a missed exit. The legacy system had the
same problem, but the spec's framing of "field-tester feedback says
current bounds are too far out" → [30s, 3s] **actively makes the
highway case worse** by keeping the far-tier at 30s.

**Impact:** A pre-existing gap isn't newly created by this spec,
but the spec's narrative ("solving the field-tester complaints")
sells a completeness that isn't there. A beta tester driving to
Flagstaff from Phoenix on I-17 may miss the 260A exit because the
only warning fires 0.56 mi out (some drivers are already
decelerating for the exit by then) and nothing primes them at 2
miles.

**Recommended resolution:** Either:
- A) Elevate NG1 to an in-scope concern with a specific design
  increment: add `highway_factor: 2` to `VOICE_TTM.auto`, applied
  when `m.type` is in `{exit_left, exit_right, ramp}` — so those
  maneuvers fire far at `60s × speed` = 1800m = 1.1 mi. Small
  change, fits in the same PR, closes the worst pre-existing
  gap the spec's framing sells as solved.
- B) Keep NG1 deferred but make the risk surface EXPLICITLY in §1:
  "TTM at interstate speed gives ~0.56 mi advance notice for exits
  — less than the ~2 mi / 1 mi / 0.5 mi cadence drivers are
  trained on by Google/Apple Maps. A future spec adds per-maneuver-
  type overrides. In the interim, drivers should treat highway
  exits as a regime where Geographica gives less advance notice
  than commercial alternatives." This tells beta testers what to
  watch for.

Do not ship with the current NG1 framing ("deferred, not a
priority") without at least acknowledging the severity asymmetry.

---

### F5.6 — NG2 deceleration deferral: "50m floor masks most drift" is numerically wrong under hard braking

**Severity:** SHOULD-FIX
**Framing question:** Does the 50m floor actually mask the 1–2 second
timing lag under deceleration, or is that claim hand-waved?

**Current spec position:** NG2: "Deceleration anticipation (using
predicted-speed-at-maneuver instead of current speed). Deferred. The
50m distance floor masks most of the 1-2 second timing drift from
hard braking."

**Challenge:** Trace the math. Driver approaching a stop sign at
10 m/s, then brakes at t=0 with deceleration 3 m/s² (moderate —
not emergency braking):
- At t=0, driver is 30m from stop sign. `speed = 10`, `ttm = 3s`.
  Near check: `3 <= 3` TRUE → near fires. `distToNext = 30m`. Voice
  says "Turn left onto Mulberry." Driver starts turning the wheel.
  Hm, but they're still going 10 m/s — that's 22 mph, too fast
  for a 90° turn. They brake harder.
- The spec's claim is this scenario is fine because the 50m floor
  catches it. But the near-tier *already fired* at 30m via the TTM
  near condition (`3s <= 3s`), not via the floor. The floor isn't
  active here.
- When is the floor load-bearing for the deceleration case?
  When `ttm > near_s` but `dist <= floor`. `ttm = dist / speed`,
  so `ttm > 3 AND dist <= 50` means `speed < dist/3`. For
  `dist = 50m`, `speed < 16.7 m/s`. So at any city/residential
  speed approaching the maneuver, the near-tier fires via the
  floor, not via TTM. The floor IS the trigger. §E5 acknowledges
  this ("TTM = 40/1 = 40s > 30s far threshold...but dist = 40m
  ≤ 50m floor, so near fires via the floor trigger").

So NG2's claim "the floor masks the 1-2 second drift" actually
means "at low speed, TTM is irrelevant; the floor is what fires
near; deceleration drift doesn't matter because TTM never fires
near at those speeds." This is a fine result but NG2 names the
wrong mechanism. The real claim is "the floor dominates below
`floor/near_s = 50/3 ≈ 16.7 m/s`; deceleration sensitivity only
matters *above* that speed, and at those speeds the driver has
already passed near-tier before they began braking."

But then there's a gap: at 17–25 m/s approaching a surface-street
maneuver (say, highway exit then immediate merge to a local road
maneuver at 50 mph), the driver is decelerating from 25 to 5 m/s
over the last 200m. TTM computed on `speedMedian() ≈ 18 m/s` at
the moment of the near-check: `200/18 = 11s`. Near threshold 3s,
so near fires at `3 × 18 = 54m` — which is above the 50m floor.
But 50m ahead the driver is actually going 8 m/s (still
decelerating) — so they had 6.7 seconds of actual time-to-
maneuver, not 3. The voice fires 3.7 seconds too early from the
driver's subjective clock. For "Turn left onto Mulberry" this
might feel reasonable (it's still an alert). For "In 150 feet,
turn left" — wait, that's the far-tier text, not near.

OK, so the near-tier at 54m fires with
`verbal_pre_transition_instruction = "Turn left onto Mulberry"`
— no distance in the string. The driver hears "Turn left onto
Mulberry" at 54m while still going 8 m/s. They can turn in ~2s.
Marginal but acceptable.

**The actually-problematic case:** driver going 15 m/s on a
residential street, brakes hard at 20m for an unexpected child,
speed drops to 2 m/s. TTM at tick with `speedMedian() = 10`
(median of `[15, 10, 2]`): `20/10 = 2s`. Near threshold 3s →
near already fired when dist was higher. Driver hears the turn
prompt at 20m but is now braking to a stop — mismatch between
voice and motion state. This is E3 in the spec, which admits a
1–2 second lag and punts it. But the "driver reaction: wait,
NOW? let me brake" framing in Cameron's task prompt IS a real
driver UX degradation, even if the floor backstops count.

**Impact:** NG2 underspecifies why deferral is safe. The actual
safety-relevant scenario is "driver going moderate speed,
brakes suddenly, prompt fires during the brake deceleration and
feels off." Spec should either address it or acknowledge it more
honestly.

**Recommended resolution:** Rewrite NG2:

"Deceleration anticipation deferred. Rationale: for approach
speeds below ~16.7 m/s (37 mph), the distance floor fires near-
tier before TTM arithmetic matters, so deceleration skew is
irrelevant. For approach speeds above 16.7 m/s, median-of-3
smoothing absorbs 1 sample of decel lag (~1s at 3 m/s²); the
driver experiences a near-prompt ~1-2s earlier than their
subjective clock would predict. Worst case, fired-too-early is
safer than fired-too-late. If beta testing surfaces specific
complaints about the `hard-brake approach + unexpectedly-early
prompt` scenario, v2 adds `predicted-speed-at-maneuver` using
last-3-tick deceleration estimate. Not in v1 scope."

This names the regime, names the mechanism, names the acceptable
worst case, and preserves the deferral.

---

### F5.7 — Beta-tester generalization: §6.4 covers ONE driving regime; urban grid / rural highway / SAR untested

**Severity:** SHOULD-FIX
**Framing question:** Does [30s, 3s] with 50m floor generalize across
Geographica's actual user regimes, or just the one Cameron drove?

**Current spec position:** §6.4 tests "3-maneuver close-cluster." §6.5
gates ship on Villa Rita re-drive. §6.1 matrix tests
speed×distance×costing cells synthetically.

**Challenge:** Geographica's user regimes per CLAUDE.md and project
ethos:

1. **SAR over mountains** — long straightaways (switchbacks), then
   dense maneuver clusters. TTM at ~20 m/s on a mountain road:
   far fires at 600m, near at 60m (above floor). Switchback
   cluster spacing ~40m: TTM enters D1 territory. Probably fine.
   Not tested.
2. **Urban grid (Phoenix city blocks)** — blocks are ~100–125m.
   At 10 m/s urban, far fires at 300m (= 3 blocks away), near
   at 50m floor. A sequence of "left, right, left, right" block-
   by-block turns at 100m spacing: each block, TTM re-enters
   near-tier territory for the next maneuver. Prompt cadence
   ≥1/block ≈ 1 prompt every 10s. Sustainable for 4-5 blocks
   becomes fatiguing over 10+.
3. **Rural highway (US-93)** — maneuvers every 15-30 miles.
   [30s, 3s] means far fires at 900m, then nothing for 15
   minutes, then fires again. Probably fine — this is the easy
   case. Not tested.
4. **Parking lot / trailhead arrival** — speeds ≤5 m/s, spacing
   ≤30m. TTM→large, everything governed by floor. For auto
   costing (floor = 50m), driver hears a near-prompt for every
   maneuver along the trailhead access road — 50m apart means
   constant prompting. Not tested.

**Impact:** The spec generalizes from N=1 field observation (Villa
Rita) without a principled argument that [30s, 3s] with 50m
floor fits the other regimes. Some of them almost certainly
look fine; others (parking lot arrival, urban grid) have
plausible failure modes the synthetic test matrix doesn't catch.

**Recommended resolution:** Expand §6.5 ship gate beyond Villa
Rita to include one test-drive per regime:

- Urban grid: downtown Phoenix 4-block hop with 4 maneuvers
  (Cameron has access to this).
- Rural highway: I-17 segment with 2+ exit maneuvers (same drive
  as the §6.5b from F5.2).
- Parking lot / trailhead: any shopping center with 2-3 turn
  sequence to a specific storefront.

Each self-reported by Cameron as "count vs subjective cadence."
Pass criterion: subjective "about right" or "slightly chatty"
across all four regimes. Fail criterion: "chatty" or "can't keep
up" on any regime → regime-specific fix before merge.

Alternatively: acknowledge in §1 that v1 is validated against
one regime (Villa Rita-style surface-street reroute) and other
regimes will be iterated in v2 based on beta feedback. Honest
scope acknowledgment beats false-coverage claim.

---

### F5.8 — Voice-picker ↔ TTM interaction, mute lifecycle, and rollback mechanism all unaddressed

**Severity:** SHOULD-FIX
**Framing question:** Does this spec compose with the in-flight
voice-picker spec, preserve existing mute UX, and provide a
rollback if beta field results are bad?

**Current spec position:**
- Voice-picker interaction: G8 claims "Composes cleanly with
  [2026-04-21-nav-voice-picker-design.md] — voice-picker acts
  on the `onVoiceCb` callback boundary, which is preserved
  unchanged." NG3 says no changes to nav-ui.js voice pipeline.
- Mute: G9 claims "Mute-state interaction unchanged: when
  muted, `announcedSet` still populates (so already-crossed
  TTM points are not re-fired when user un-mutes mid-route)."
  I8 restates this.
- Rollback: not mentioned. Band-aid removal is an all-or-
  nothing change per §8.

**Challenge:**

**8A — Voice-picker interaction is underspecified for the preview
case.** Per voice-picker v2 spec §9.1, "`previewArmed` is reset
on sidebar-close or 30-second idle." Voice-picker preview fires
an utterance via `speechSynthesis.speak()` on the same synthesis
channel as TTM. If TTM fires a near-prompt at T, and the user
opens the Preferences sidebar at T+2s and previews a voice at
T+3s, the voice-picker spec calls `speechSynthesis.cancel()`
before its preview utterance — which cancels the *in-flight*
TTM prompt mid-speech. From the driver's perspective, they
hear "Turn left onto Mul—" cut off. This is pre-existing
behavior (any cancel affects all utterances on a shared
synthesis channel), but the TTM spec should name it:
interaction with voice-picker preview is undefined when the
driver previews during active nav. Voice-picker v2 has a
nav-active guard (`document.body.classList.contains
('nav-active')` early-returns preview), so this is actually
SAFE — but the TTM spec doesn't document the dependency.

**8B — Mute UX: "mute forever" is the only mode.** Cameron's task
prompt asks whether a driver can "mute for 5 minutes" or "mute
until next reroute." Current behavior (per `nav-ui.js:731`):
mute toggles a binary flag persisted in localStorage. Unmute
requires another button press. This spec preserves that — I8
confirms. But the spec *could* add "auto-unmute on reroute"
semantics, since reroute clears `announcedSet`. The question
is whether a driver who muted during a dangerous moment
(construction zone, sudden storm) wants silence to persist
indefinitely. Arguably no — the user intent was "shut up for a
few minutes while I focus," not "shut up forever." Not
adding this is a valid choice, but the spec doesn't articulate
*why* the choice is preservation rather than improvement. If
the answer is "out of scope," say so explicitly.

**8C — No rollback mechanism documented.** The 2026-04-20
handoff explicitly notes the band-aid was shipped as
`e63f6d9` with a clear revert path. The TTM spec §8 says "Do
NOT land TTM without removing the band-aid in the same PR —
the two are designed as a unit." But if TTM fails the §6.5
field gate, the rollback is "git revert the PR," which
reintroduces the band-aid (fine) and also removes D1 and the
median smoothing (also fine, since they were net-new). What's
*not* fine is if TTM ships, passes §6.5 with Cameron, and
then a week later a beta tester reports "my nav is silent on
half my turns." At that point, reverting is a user-facing
regression unless announced. Spec should articulate:

- First-week flag gate? ("TTM active iff
  `localStorage.ttm_enabled !== 'false'`; add a sidebar
  toggle under Preferences")
- Or a confident no-flag ship ("TTM is the system; if it
  breaks we fix forward")?
- Or preserve the band-aid constants as a dormant fallback
  controlled by a feature flag?

**Impact:**
- 8A is cosmetic / already-guarded; the spec should just add
  a sentence naming the dependency.
- 8B is a missed product opportunity; spec should either add
  auto-unmute-on-reroute or explicitly reject it with
  reasoning.
- 8C is the actual shipping-discipline hole. The spec's "merge
  the PR, delete the band-aid, done" is the maximalist
  approach. Given that the Villa Rita 9-prompt failure
  shipped despite green tests, the rollback story deserves
  more than an unwritten "we'll revert if it breaks."

**Recommended resolution:**
- Add §3 sentence: "Voice-picker preview interactions with
  TTM are gated by voice-picker v2's `nav-active` guard; no
  TTM-side change required."
- Add to NG7 or new §NG10: "Auto-unmute on reroute is out of
  scope for v1. If beta testers report 'missed turns after
  mute,' v2 adds `reroute_unmutes: true` as a Preferences
  toggle. Current behavior (mute persists across reroute) is
  preserved."
- Add §10 step 7b or §8 new item: "Rollback posture: TTM ships
  without a runtime flag. If §6.5 field drive fails, the PR
  is reverted in its entirety, reinstating the band-aid. If
  a post-ship field report surfaces a TTM-specific regression
  within the first 7 days post-merge, revert is acceptable;
  after 7 days, fix-forward is expected. No parallel-systems
  feature flag — the spec §8 rationale (two thresholds
  fighting for who fires first) applies equally to a flag-
  gated rollback."

---

### F5.9 — §6.5 manual field drive underspecifies data capture; recurrence risk

**Severity:** SHOULD-FIX
**Framing question:** The post-mortem on the 2026-04-20 nav UX
remediation said green unit tests coincided with the 9-prompt
field disaster. What's different about this spec's field gate that
prevents the same thing happening again?

**Current spec position:** §6.5: "Before merge, re-drive the Villa
Rita → Costco westerly-detour route from the 2026-04-20 field
observation. Count voice prompts. Ship criteria: Pass: ≤ 3 prompts
for the rerouted 3-maneuver cluster. Fail → investigate. Unit
tests alone are insufficient for ship sign-off."

**Challenge:** The §6.5 spec has three underspecifications:

1. **Who drives it?** "Cameron" is implicit but not stated. If
   Cameron is unavailable (sick, traveling, busy with $DAYJOB),
   can a beta tester drive it and report? If so, which beta
   tester? What's the handoff?
2. **What data is captured?** "Count voice prompts" is the
   criterion, but a post-hoc count from memory is exactly what
   produced the 9-prompt observation, and that observation may
   itself be off by ±2 (human memory under cognitive load is not
   reliable for sequential-event counts). The spec should
   require:
   - GPS track (so the route is reproducible for regression)
   - Audio log (phone's speaker capture via a second device, or
     the phone's own screen recording audio channel)
   - Timestamped prompt log (engine-side hook emitting each
     `onVoiceCb` invocation to console.log, captured via
     devtools remote)
3. **What's the feedback loop to v2?** If §6.5 fails, the spec
   says "Do not re-tune thresholds as a shortcut — root-cause
   the drift." That's good discipline, but "root-cause" with
   what evidence? If the only evidence is "Cameron says there
   were 6 prompts," the root-cause investigation has no
   artifacts to chase. Same failure mode as 2026-04-20.

**Impact:** The spec's ship gate is only as good as its evidence
capture. An unartifacted "count prompts and tell me" protocol
risks recapitulating the exact post-mortem gap this round of
work was supposed to close.

**Recommended resolution:** Rewrite §6.5:

"**§6.5 Manual field regression gate — ship blocker.**

Pre-requisite instrumentation: before the drive, add a temporary
(removed in a follow-up commit) log hook in `navigation.js`:

```js
// TEMP: field-drive prompt log — remove after §6.5 gate passes
if (!muted && onVoiceCb) {
  console.log('[TTM-field]', Date.now(), 'tier=', tier,
              'dist=', distToNext.toFixed(1),
              'ttm=', ttm.toFixed(1),
              'speed=', speed.toFixed(1),
              'text=', text);
  onVoiceCb(text);
}
```

Drive: Cameron (primary driver for this gate). If Cameron is
unavailable for >48h past merge-ready, a beta tester with GPS-
hat-equipped phone may substitute; the §6.5 gate then becomes
're-drive Villa Rita AND report the log'.

Data capture:
- GPS track: gpsd log on the phone-side, or a screen recording
  that captures the Geographica map trajectory.
- Audio log: screen recording of the drive captures the speaker
  audio.
- Timestamped prompt log: devtools remote debug or adb logcat
  capturing `[TTM-field]` console messages.

Pass criteria (ALL must hold):
- Audio log prompt count ≤ 3 for the Villa Rita cluster.
- Log-timestamped prompt count matches audio prompt count
  (cross-check that no prompt was silently queued or
  suppressed).
- Cameron's subjective rating: 'appropriate' or 'slightly
  sparse' (not 'too chatty' or 'missed a turn').

Fail → do not merge. Root-cause investigation uses the GPS
track + log + audio. Evidence is the artifact, not the human
count."

This closes the evidence gap. Add the instrumentation removal
to §10 step 7 ("Runtime validation on live stack") as step 7c:
"Remove the `[TTM-field]` debug log in a follow-up commit."

---

## Summary

- **9 findings.** MUST-FIX: F5.1 (Villa Rita math is scenario-brittle),
  F5.2 (highway regression vs band-aid). SHOULD-FIX: F5.3–F5.9.
- **Pattern across findings:** the spec sells itself on a specific
  scenario (Villa Rita 9→3) and a specific user complaint ("too far
  out") without interrogating whether the chosen parameters
  generalize beyond that scenario. The accounting is correct for the
  example; the generalization claim is hand-waved. Roughly half the
  findings (F5.1, F5.2, F5.7) are variants of this "N=1 field
  evidence, spec-wide conclusion" pattern.
- **The one most worth Cameron's attention:** F5.2. TTM at highway
  speed is *looser* than the band-aid. If a beta tester drives I-17
  with TTM and reports "the nav got chatty again," the spec's
  narrative ("we fixed the chattiness") will be falsified by its own
  shipped system. Either ship [20s, 3s] instead, or run the §6.5b
  highway drive before merge.
- **Runner-up:** F5.3 (D1 information-starvation risk on reroute).
  D1 was designed for the reroute scenario; the spec then removes
  advance-notice framing from exactly the scenario where the driver
  needs it most. One-flag fix (`firstAfterReroute`) closes it cheaply;
  the spec should at minimum name the tradeoff.
- **Cameron-ethos hook:** project ethos says "process rigor > raw
  velocity." The band-aid shipped too fast because field evidence
  wasn't captured; the TTM spec is about to ship with the same
  evidence gap (F5.9). Instrumenting §6.5 is a direct application of
  the lesson from 2026-04-20.

None of the findings are veto-worthy — TTM is the right direction.
But F5.1/F5.2 are load-bearing for the spec's top-line safety claim
and should not ship without resolution.
