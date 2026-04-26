# Nav voice follow-up — Round 3 adversarial (numerical + formatting)

**Date:** 2026-04-24
**Agent:** pinyon-sub-r3
**Spec under review:** [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md)
**Lens:** boundary math, rounding semantics, float quirks, TTS formatting, speech-time cannibalization
**Methodology:** re-implemented §5.1 spec in Node, replayed the 21 test vectors in §5.5, fingerprinted the `stripBakedDistance` regex against a live Valhalla response from the running stack (Villa Rita area, canonical route query), verified JS `Math.round` / `toFixed` semantics at every band boundary, computed speech-duration deltas from word counts.

---

### F3.N-1 — `formatDistancePrefix(950, false)` expected value is wrong (JS `toFixed` bug)

**Severity:** MUST-FIX

**Claim.** Spec §5.5 lists `formatDistancePrefix(950, false) === "In 1.0 kilometers, "`. With the spec's own formula `(meters/1000).toFixed(1)`, this returns `"0.9"`, not `"1.0"`:
```
> (0.95).toFixed(1)
'0.9'
> (950/1000).toFixed(1)
'0.9'
```
JS `toFixed` uses round-half-to-even (IEEE 754) plus binary-float noise; `0.95` is not exactly representable and rounds down. The test vector as written is mathematically unreachable by the spec'd implementation.

**Impact.** The test as written will fail immediately on landing the implementation. A developer will either (a) patch the test to match the implementation (papering over a user-facing inconsistency — see F3.N-2) or (b) patch the implementation to match the test (requiring a switch away from `toFixed`), either of which represents a spec-internal contradiction that should be resolved in review, not at implementation time.

**Recommendation.** Replace the test vector with a value that is internally consistent. Either:
- Change the expected output to `"In 0.9 kilometers, "` (match `toFixed` behavior), OR
- Specify a non-`toFixed` rounding rule (e.g., `Math.round(meters / 100) / 10` — produces `1.0` for `950`), and revise every test vector and edge case accordingly.

Also: add an explicit note in §5.1 that `Number.prototype.toFixed` rounds half-to-even in the binary-float-noise regime, so implementers don't assume "round half up."

---

### F3.N-2 — User-facing regression at the 900 m boundary ("In 900 meters" → "In 0.9 kilometers")

**Severity:** MUST-FIX

**Claim.** The spec's metric rules produce a jarringly *smaller-sounding* number when distance increases across the 900 m boundary:

| distance | spec output | commentary |
|---|---|---|
| 874 m | "In 850 meters" | 50-rounding floors |
| 875 m | "In 900 meters" | 50-rounding ceils to boundary |
| 899 m | "In 900 meters" | still in 50-rounding band |
| **900 m** | **"In 0.9 kilometers"** | switched to km band — `(0.9).toFixed(1) = "0.9"` |
| 950 m | "In 0.9 kilometers" | `(0.95).toFixed(1) = "0.9"` — F3.N-1 |
| 999 m | "In 1.0 kilometers" | finally rounds up |

A driver at 898 m hears "In 900 meters, turn"; same driver two seconds later at 895 m hears "In 0.9 kilometers, turn." This is the metric analogue of "In 1000 feet → In 1/4 mile" but far more confusing because the numerical value drops from 900 down to 0.9.

**Impact.** Drivers will perceive the TTS as inconsistent and buggy. (Compare: Google Maps smooths this transition by using "In half a kilometer" / "In 800 meters" ranges that don't compete.)

**Recommendation.** Either:
- Move the metric/km boundary to 1000 m (so 899 m → "In 900 meters", 900 m → "In 900 meters", 1000 m → "In 1.0 kilometers"), AND
- Use `Math.round(m/100) / 10` for km rounding to avoid `toFixed` quirks.

Or: use fractional-km phrasing for the 500–1000 m range ("In half a kilometer", "In 1 kilometer") to match the Google Maps convention the spec cites.

---

### F3.N-3 — `stripBakedDistance` `(?=[A-Z])` guard is defeated by the `/i` flag

**Severity:** MUST-FIX

**Claim.** The `stripBakedDistance` regex in §5.1 is:
```js
var BAKED_DISTANCE_RE = /^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km|m)\s*,\s*(?=[A-Z])/i;
```
The `/i` flag makes the regex case-insensitive *everywhere*, including inside the lookahead. So `[A-Z]` matches both upper and lower case. The spec's §5.1 negative test vector claims:
```
stripBakedDistance("In 400 feet, you will turn.") === "In 400 feet, you will turn." (no-op)
```
Actual behavior (verified by running the spec'd regex in Node):
```
> "In 400 feet, you will turn.".replace(BAKED_DISTANCE_RE, "")
'you will turn.'
```
The `"you will turn."` strip is a FALSE POSITIVE — the guard was supposed to prevent it, but `/i` silently defeats the guard.

**Impact.** Any Valhalla output that legitimately starts with "In <number> <unit>, <lowercase instruction>" will be mis-stripped, producing a chopped-off instruction. Example (fabricated but plausible for an SSML-normalized maneuver): `"In 400 feet, you will turn left."` → stripped to `"you will turn left."` → with the spec's prefix-prepend, `"In 200 feet, you will turn left."`. Double-stating the distance is exactly what G8 promised to avoid.

More concretely: the spec's §5.1 test vector table would show the last case as a PASS when it actually FAILS. A reviewer running the tests finds the truth, but only after landing.

**Recommendation.** Either:
- Drop the `/i` flag and explicitly lowercase-first-letter the `In` match: `/^[Ii]n\s+…/` (no flag). OR
- Split: use `/i` only on the leading `[Ii]n` with `(?=[A-Z])` as a separate anchored test after strip, OR
- Use a case-sensitive regex `/^In\s+…\s*,\s*(?=[A-Z])/` and cover "in" case with a pre-uppercase pass.

Also: add a test vector `stripBakedDistance("in 400 feet, Turn left.") === "Turn left."` to pin down the desired behavior for Valhalla's observed lowercase-"in" output (see F3.N-4).

---

### F3.N-4 — Valhalla output shape defeats the pre-existing `.Then\s+` strip, making the spec §5.2 "preserved" claim false

**Severity:** MUST-FIX (spec misrepresents baseline behavior)

**Claim.** Spec §5.2 says: *"Existing Then strips are preserved (load-bearing — they remove Valhalla's baked chain so I11 suppression is semantically correct)."*

The actual Valhalla output (verified against the live stack, query: `{33.6810,-112.1087 → 33.6540,-112.1150}`) for `verbal_pre_transition_instruction` is:

```
M1: "Turn left onto West Deer Valley Road. Then, in 700 feet, Take the I 17 South ramp on the right."
M0: "Drive north on North 23rd Avenue. Then, in a quarter mile, Turn left onto West Deer Valley Road."
```

Note `"Then, "` — a comma follows "Then." The existing regex is `/\.\s*Then\s+[^.]*\.?\s*$/i`. `Then\s+` requires **whitespace** directly after "Then" — but Valhalla emits **comma-then-whitespace**. The strip FAILS to match. Verified:

```
> "Turn left. Then, in 700 feet, Take the ramp."
    .replace(/\.\s*Then\s+[^.]*\.?\s*$/i, ".")
'Turn left. Then, in 700 feet, Take the ramp.'   // unchanged
```

So the spec's claim that the existing strip "preserves" proper suppression is false — the strip was never doing anything in production. This is a pre-existing bug, BUT the spec has built its semantics atop the false assumption. If a maintainer fixes the strip regex (`\.\s*Then[,\s]+…`), the near-tier text on every real Villa Rita → Costco maneuver changes; the Villa Rita prompt-count invariant in G7/G11 becomes dependent on whether the strip is actually working.

**Impact.** (a) Spec documentation is lying about baseline behavior. (b) Post-ship, if anyone tightens the regex to close the observed-in-the-wild bug, the §5.4 expected transcripts and the invariant-count tests both shift silently. (c) The "spec-compliant" output in §5.4 assumes the baked chain is already stripped from Valhalla text — but if the strip never runs, then the spec-compliant output would be something like `"In 200 feet, turn left onto North 21st Avenue. Then, in 700 feet, take the I 17 South ramp, then in 1/4 mile, turn left onto West Union Hills Drive."` — TRIPLE distance phrasing.

**Recommendation.**
1. Fix the existing strip regex in this spec: `/\.\s*Then[,\s]+[^.]*\.?\s*$/i` (accept `,` after "Then" as well as whitespace).
2. Re-derive the §5.4 expected-transcripts table against real Valhalla output, not against an idealized "baked-chain-free" baseline.
3. Add a regression test that pipes a fixture `"X. Then, Y."` through the full `checkVoice` and asserts the trailing clause is gone.

---

### F3.N-5 — Test vector in §5.5 contradicts the 100 ft cutoff (chain-append at 30 m spacing)

**Severity:** MUST-FIX

**Claim.** §5.5 includes:
> `TTM I13: chain-append carries its own distance prefix — run fixtureVillaRitaCluster (30 m spacing), assert near-tier text contains ", then in 100 feet, " (30 m * 3.28 = 98 ft → rounds to 100)`.

The imperial branch of `formatDistancePrefix` says `<100 ft: ""` (spec §5.1). At 30 m input, `30 × 3.28084 = 98.43 ft`, which is `< 100`, so the formatter returns `""` — no prefix. The spec's own cutoff suppresses the output this test asserts.

Contradiction: the test vector expects `"in 100 feet"` to appear in the chain-append string, but the formatter will return `""` and the chain will read `", then turn right"` (no prefix).

**Impact.** The test as written will fail.

**Recommendation.** Either:
- Change `fixtureVillaRitaCluster` spacing to 31 m (or 35 m) so `ft > 100` and the prefix-path is exercised, OR
- Change the test assertion to `, then turn right` (no prefix — which exercises the cutoff guard), OR
- Unify the cutoff between metric (30 m) and imperial (100 ft ≈ 30.48 m) — they are drifted by half a meter today, see F3.N-6.

---

### F3.N-6 — Mismatched cutoffs between the helper-level constant and the imperial branch

**Severity:** SHOULD-FIX

**Claim.** §5.1 defines:
```js
var DISTANCE_PREFIX_CUTOFF_METERS = 30; // ≈ 100 ft
```
but the imperial branch says `<100 ft: ""`, and `100 ft = 30.48 m`. So between `30.00 m` and `30.48 m`:
- Metric branch (`m < 30`) returns `""` ✓ consistent with named constant
- Imperial branch (`ft < 100`) returns `""` — but the distance IS above `DISTANCE_PREFIX_CUTOFF_METERS`, so the named constant doesn't describe imperial

The constant is not the source of truth; it's a metric-only cutoff with `"≈ 100 ft"` as a comment. A reader assumes the imperial cutoff is ALSO 30 m.

**Impact.** Minor semantic drift. Consistent with the observed §5.5 test-vector bug in F3.N-5 — the author conflated 30 m with 100 ft.

**Recommendation.** Pick one:
- Unify on 30 m: imperial cutoff becomes `ft < 30 × 3.28084 ≈ 98.4` (or just `meters < 30`).
- Unify on 100 ft (30.48 m): metric cutoff becomes `meters < 30.48` or round to 30 m but declare the imperial branch authoritative.

Then rename the constant to reflect the unit it governs. Doing this also resolves F3.N-5 cleanly.

---

### F3.N-7 — TTS pronunciation of `"1/4 mile"` is engine-dependent and not verifiable from the spec

**Severity:** SHOULD-FIX (empirical gap — needs live verification before ship)

**Claim.** §5.1 imperial band outputs strings like `"In 1/4 mile, "`. The spec assumes the Web Speech API engine (iOS Safari, Chromium on Pi) pronounces `"1/4 mile"` as `"one quarter mile"` or `"one-fourth mile"` — a speech-readable form.

Research summary:
- **MDN SpeechSynthesis docs** do not document fraction handling; it is entirely engine-specific.
- **iOS Safari (Siri voices)** typically pronounce `"1/4"` as `"one quarter"` when adjacent to a unit noun, but standalone `"1/4"` can be read as `"January 4"` (date heuristic) or `"one-fourth"`. With `"1/4 mile"` the unit disambiguates, but this is undocumented.
- **Chromium TTS (Google voices)** generally pronounces `"1/4 mile"` as `"one quarter mile"`, but older engines (eSpeak) can say `"one slash four mile"`.
- **The Pi's Chromium** defaults to eSpeak for non-English fallback — a beta tester on a Linux rig may hear `"one slash four"`.

The spec's §5.4 expected transcripts (e.g., `"In 1/4 mile, turn right onto North Black Canyon Highway"`) are silent on the SPOKEN form — only the text form is tested. No unit test or integration test verifies that the TTS engine produces an intelligible utterance. This is an untested output contract for an audible user surface.

**Impact.** On a mis-configured browser or exotic TTS voice, drivers hear `"In one slash four mile, turn right"` — actively confusing during driving. The field-test gate §7 will catch this only if Cameron happens to have a voice that pronounces `"1/4"` literally — unlikely on his iPhone, common on Android + eSpeak + some Pi-side preview cases.

**Recommendation.**
1. Change the imperial strings to spelled-out fractions to eliminate the risk: `"In a quarter mile, "`, `"In a third of a mile, "`, `"In a half mile, "`, `"In three quarters of a mile, "`, `"In 1 mile, "`. Every TTS engine pronounces these unambiguously.
2. Alternatively: keep `"1/4"` but add a cross-engine verification step to the ship gate — have Cameron sample-utter each band with the two most common voices (en-US-Samantha on iOS, the default Linux/Chromium voice) and confirm intelligibility.
3. If the spec keeps `"1/4"`, add an integration-test harness that uses `SpeechSynthesisUtterance.onboundary` events to ensure the spoken-word count matches `"one quarter mile"` (3 words) rather than `"one slash four"` (3 words — same count, so this heuristic fails). Empirically there is no way to auto-test this without a recording rig; use spelled-out forms instead.

See also the Valhalla grounding: Valhalla's own `verbal_pre_transition_instruction` uses `"in a quarter mile"` (spelled out). The spec would produce a MIXED vocabulary on the same drive — engine-prefixed `"In 1/4 mile, ..."` on the first clause and Valhalla-baked `"in a quarter mile"` on any un-stripped clause — which is internally inconsistent.

---

### F3.N-8 — §9 speech-time-cannibalization estimate (~0.7 s) is low by ~40–70%

**Severity:** SHOULD-FIX (design math correction)

**Claim.** §9 says: *"adding a distance prefix consumes ~0.7 s of TTS, reducing the net buffer improvement from +1.3 s to +0.6 s at 25 mph."*

Word-count based speech-duration math (TTS rate ≈ 150 wpm = 2.5 words/s; fast voices push to 180 wpm):

| base text | prefixed text | Δ (150 wpm) | Δ (180 wpm) |
|---|---|---|---|
| `"Turn right onto North Black Canyon Highway"` (7 w) | `"In 1/4 mile, turn right onto North Black Canyon Highway"` (10 w) | **+1.20 s** | +1.00 s |
| `"Turn left onto West Utopia Road"` (6 w) | `"In 1/4 mile, turn left onto West Utopia Road"` (9 w) | **+1.20 s** | +1.00 s |
| `"Turn left onto North 21st Avenue, then turn left onto West Union Hills Drive"` (14 w) | `"In 200 feet, turn left onto North 21st Avenue, then in 1/4 mile, turn left onto West Union Hills Drive"` (20 w) | **+2.40 s** | +2.00 s |
| `"Turn right, then turn right"` (5 w) | `"In 100 feet, turn right, then in 100 feet, turn right"` (11 w) | **+2.40 s** | +2.00 s |

At the 25 mph symptom speed (§4.2), the floor-lift buys +1.3 s. The actual single-prefix cost is ~1.2 s (at 150 wpm), which nearly wipes out the gain. For chain-append cases (the 30 m spacing scenario Cameron actually field-tested!), the prefix cost is **+2.4 s** — the driver hears **4+ seconds** of additional TTS compared to baseline, overshooting the +1.3 s gain by nearly 1 second. Net effect: chain-append prompts at 25 mph will finish speaking *AFTER the driver broaches the intersection*, which is the exact symptom Issue 1 is trying to fix.

**Impact.** Issue 1 and Issue 2 are anti-coupled: fixing text context makes timing worse for the double-prefix case. The spec §9 math understates this and so the design reads as a net win when it's actually a regression for the most common Villa Rita symptom (30 m-spacing chain-append).

**Recommendation.**
1. Replace the "~0.7 s" estimate with the computed range (1.0–1.2 s single, 2.0–2.4 s chain-append).
2. Either:
   - Raise the auto floor further for the chain-append case (to cover the +2.4 s, floor needs to be ~65 + 25 = ~90 m, buying +3.0 s of headway), OR
   - Omit the distance prefix on chain-appends where `text` already contains a `", then "` clause (keep prefix only on the primary maneuver), OR
   - Omit the "then in N feet, " prefix specifically and keep "then turn right" style on chain-appends to avoid doubling TTS time.
3. Add a field-test acceptance criterion explicitly scoped to chain-append cases: "Seg 0 near+chain (the 30 m spacing cluster) completes speech ≥ 2 seconds before broaching the first intersection at 25 mph."

---

### F3.N-9 — "Jarring" feet→miles transition at 999 ft ↔ 1001 ft (by design, but unexamined)

**Severity:** LOW (documentation / UX clarification)

**Claim.** Spec §5.1 defines the feet band as `[100, 1000) ft rounded to nearest 100` and the next band as `[1000, 5/16 mi) = [1000, 1650) ft → "1/4 mile"`. Under the rounding rule:

- 951 ft → rounds to 1000 → "In 1000 feet, turn"
- 999 ft → rounds to 1000 → "In 1000 feet, turn"
- 1000 ft → not in feet band → `[1/4 mile]` → "In 1/4 mile, turn"
- 1001 ft → `[1/4 mile]` → "In 1/4 mile, turn"

So a driver at 950 ft hears "1000 feet" and two seconds later at 920 ft still hears "1000 feet" (good — stable), but if the driver is at 1000 ft and the update catches them on the miles-band side, they hear "1/4 mile" even though they are less than 1000 ft from the maneuver. The numerical value drops from "1000" to "1/4" — another analogue of F3.N-2's 900 m → 0.9 km issue.

**Impact.** Minor. A driver who hears back-to-back announcements "in 1000 feet, turn left" then "in 1/4 mile, turn left" may momentarily think the distance grew when it shrank.

**Recommendation.** Two options:
1. Extend the feet band to `[100, 1320) ft` (1/4 mile exact = 1320 ft), so 1000 ft announces as "1000 feet" and 1319 ft announces as "1300 feet" — next band starts at 1/4 mile = 1320 ft rounding to "1/4 mile". No overlap, no numerical regression.
2. Accept the current design but update §5.4 / field-test notes to flag this as "known minor UX nit, not a ship blocker."

Google Maps (the cited reference) uses option 1: feet readouts extend through 1300 ft and only switch to "0.2 miles" above that. Recommend adopting.

---

### F3.N-10 — 100 m cutoff rule ambiguity at the boundary

**Severity:** LOW (spec clarity)

**Claim.** §5.1 says metric:
```
<100 m: rounds to 10
>= 100 m: rounds to 50
```
At exactly `100 m`, which rule applies? Spec text uses `>=` for the ≥ 100 branch, so 100 triggers the 50-rounding path. Actual output from `round(100/50)*50 = 100 → "In 100 meters, "`. Still fine, but there is also a jump from "rounded to 10" → "rounded to 50" which means:
- 94 m → `round(94/10)*10 = 90` → "In 90 meters"
- 99 m → `round(99/10)*10 = 100` → "In 100 meters"
- 100 m → `round(100/50)*50 = 100` → "In 100 meters"
- 124 m → `round(124/50)*50 = 100` → "In 100 meters" (dwells at 100 for 25 m)

This is NOT a bug — it's actually smooth. But the spec doesn't explicitly confirm the `>=` vs `>` boundary, and the §5.5 test vectors skip this boundary.

**Impact.** Ambiguity risk: an implementer might code `m < 100` for one branch and `m < 100` again for the other, creating an unreachable case. Trivial to catch in review, but spec should be unambiguous.

**Recommendation.** In §5.1, change the phrasing to:
```
30 <= m < 100: rounds to 10
100 <= m < 900: rounds to 50
m >= 900: N.N kilometers
```
And add test vector `formatDistancePrefix(100, false) === "In 100 meters, "` to pin the boundary.

---

### F3.N-11 — "In 2.0 kilometers" trailing `.0` is grammatically awkward for TTS

**Severity:** LOW

**Claim.** At exactly 2000 m, spec §5.1 computes `(2000/1000).toFixed(1) = "2.0"` → `"In 2.0 kilometers, "`. The TTS engine reads this as `"In two point zero kilometers"` — grammatically valid but verbose and unnatural. `"In 2 kilometers"` is the natural phrasing.

**Impact.** Minor UX polish. The "2.0" form adds ~0.5 s of TTS time (the "point zero" words) for zero information gain. It also creates disfluency: "In two POINT zero kilometers, turn right" reads like a data readout, not driving guidance.

**Recommendation.** In the km branch, strip a trailing `.0`:
```js
var km = (m / 1000);
var kmStr = km.toFixed(1);
if (kmStr.endsWith(".0")) kmStr = kmStr.slice(0, -2);
return "In " + kmStr + " kilometer" + (kmStr === "1" ? "" : "s") + ", ";
```
Also add singular/plural handling for `1` km vs `1.5` km: spec's current formula would say `"In 1.0 kilometers"` (plural, weird) when the natural phrasing is `"In 1 kilometer"` (singular). Verify: `(1.0).toFixed(1) === "1.0"`, `(1.5).toFixed(1) === "1.5"`. The spec has no plural rule at all.

Also flag: the `"In 2 miles"` case IS plural-correct (spec uses "miles" always above 3/2 mile). But `"In 1 mile"` is correctly singular per §5.1 — good.

---

### F3.N-12 — Feet band can legitimately say "1000 feet" but the spec forgets it when documenting bands

**Severity:** LOW (internal-consistency nit)

**Claim.** §5.1 documents the feet band as:
```
[100, 1000) ft: "In N00 feet, " (rounded to nearest 100)
[1000, 5/16 mi) ft: "In 1/4 mile, "     (1000–1650 ft)
```
The feet band is `[100, 1000)` (exclusive on 1000), but the rounding rule `round(ft/100)*100` can produce `1000` as output (for any `ft ∈ [950, 1000)`). So the band's literal range is `[100, 1000)` but the output range is `[100, 1000]` (inclusive). The spec's test vector correctly captures this:

> `formatDistancePrefix(290, true) === "In 1000 feet, "` with note *"feet-band's output can legitimately say 1000 feet"*

So the spec is internally consistent HERE, but the band-header comment `[100, 1000) ft` is misleading if a reader looks only at the headline bands. Minor.

**Impact.** Only confuses readers who skim §5.1 without reading the §5.5 notes.

**Recommendation.** In §5.1, annotate the feet band header as `[100, 1000) ft input → rounded output in {100, 200, …, 1000}`. Alternatively, tighten the band to `[100, 950) ft` (so rounding can't produce 1000) — but this breaks the Google Maps convention cited in the spec. Documentation clarity is the cheaper fix.

---

### F3.N-13 — Chain-append double-distance utterance is cognitively overloaded

**Severity:** MUST-FIX (UX — spec lays out the symptom itself but does not commit to a resolution)

**Claim.** Spec §5.4 row 1:
> Seg 0 near+chain · fire @ 65 m, M2 @ 459 m → **In 200 feet**, turn left onto North 21st Avenue, **then in 1/4 mile**, turn left onto West Union Hills Drive

The driver hears TWO distance references in one utterance: "In 200 feet" and "in 1/4 mile." This is:
1. ~20 words of continuous TTS at 25 mph (8 s at 150 wpm) — longer than the pre-maneuver buffer even after Issue 1's floor lift (5.8 s at 65 m, 25 mph per §4.2).
2. Cognitively busy — driver must parse "In 200 feet do X, then in 1/4 mile do Y" while actively approaching a T-intersection. Modern driver-assist guidance (Waze, Google Maps, Apple Maps) limits themselves to ONE distance per utterance for this reason.

**Impact.** Under the current design, at 25 mph the driver is still mid-speech when they reach the first turn, AND they have to remember the second distance/turn for the following maneuver. Worse than today's terse chain-append.

**Recommendation.**
1. Drop the distance prefix on the chain-append clause; keep only the primary. Output: `"In 200 feet, turn left onto North 21st Avenue, then turn left onto West Union Hills Drive."` (13 words vs 20 words, saves ~2.8 s).
2. OR: if the chain-append's maneuver is distant enough that its own far-tier will fire separately, drop the chain-append entirely (already the existing behavior above `NEXT_AFTER_NEXT_DISTANCE = 500 m`). But the 459 m case falls just under — consider lowering that threshold to 300 m, keeping chain-append only for genuinely-tight clusters.
3. Update the field-test gate to check "chain-append utterances are < 2 s at the symptom speed" as a hard gate.

See F3.N-8 for the corroborating speech-time math.

---

### F3.N-14 — Boundary-foot jitter: 1649 ft → "1/4 mile" vs 1650 ft → "1/3 mile" at 1-foot resolution

**Severity:** LOW

**Claim.** §9 flags this explicitly as an open question. Verified:
- 1649.99 ft (~502.9 m) → "1/4 mile"
- 1650.00 ft (~502.9 m) → "1/3 mile"
- ~1 second of driver movement at 25 mph (37 ft) is enough to cross 3 such boundaries on a long approach.

The driver could hear "In 1/4 mile, turn left" at 1649 ft, "In 1/3 mile, turn left" one second later at 1686 ft — direction of change (number goes up when distance is going down) confuses.

**Impact.** In the far-tier (fires once per maneuver), only ONE boundary announcement happens per maneuver, so this is usually invisible. But on long highway approaches where TTM fires the far-tier early and re-computes, a second re-fire could exhibit this.

Under the current TTM v3 design the far-tier fires exactly once per maneuver (I1 invariant). So this is a LOW severity — invisible in production. But if a future re-fire mechanism is added (e.g., the "are you sure the maneuver is still upcoming" re-announcement some nav apps do), this becomes visible.

**Recommendation.** Document that the boundary jitter is intentionally ignored because far-tier fires exactly once per maneuver (I1). Add a forward-compat note: "if a re-fire mechanism is introduced, hysteresis will be needed on band membership."

---

### F3.N-15 — Cutoff of `""` (no prefix) breaks the §5.1 return-type contract ambiguity with falsy checks

**Severity:** LOW (defensive coding)

**Claim.** §5.1 says `formatDistancePrefix` returns `""` (empty string, falsy) when below cutoff. §5.2 uses `if (farPrefix && farText.length > 0)` to guard — good, falsy check. But the chain-append path uses `if (afterPrefix)` alone — also good, both guards are functionally equivalent for the `""` case.

BUT: what if a future contributor changes `""` → `undefined`, or vice versa? Then `"In 100 feet, " + undefined = "In 100 feet, undefined"` — a disaster. The spec documents the contract in prose but not in a typed signature (no JSDoc `@returns {string}`). Also: the `.charAt(0).toLowerCase()` call in §5.2's prepend path will throw if `afterPrefix === undefined`.

**Impact.** Low today, medium if the helper is ever refactored.

**Recommendation.** Add an explicit JSDoc `@returns {string}` and either (a) document that `""` is the sentinel, not `null`/`undefined`, or (b) change the API to return `null` and handle it uniformly with `if (prefix !== null)`.

---

### F3.N-16 — `_geographicaUseImperial` global read bypasses the callback boundary preserved in NG5

**Severity:** LOW (architectural hygiene)

**Claim.** NG5 says: *"The `onVoiceCb(text)` boundary is preserved; text is formed inside `navigation.js` and handed to `nav-ui` unchanged in shape."* But §5.3 introduces `_geographicaUseImperial()` reading a window global at engine-call time:

```js
function _geographicaUseImperial() {
  return typeof window !== 'undefined' && window._geographicaUseImperial !== false;
}
```

This is a NEW cross-module coupling. The engine previously only read callback-provided state. Now it reads a global. On the jsdom test harness where `window._geographicaUseImperial` is `undefined`, the function returns `true` (default imperial) — but what if a test wants to exercise the metric branch? It must monkey-patch the global. The spec §5.5 says *"TTM I13: imperial vs metric dispatch — toggle `_geographicaUseImperial`, run same fixture, assert text switches feet/meters"* — so the test DOES monkey-patch. Fine at test time, but new coupling.

**Impact.** Minor architectural drift. The engine is no longer a pure function of (route, snapshot); it depends on an ambient global. This could bite future refactors (e.g., server-side rendering the navigation engine).

**Recommendation.** Pass `useImperial` as a parameter to `checkVoice` (already called from nav-ui which has direct access to the flag). This keeps the existing callback-boundary contract — no global reads in the engine.

---

## Summary

**Count by severity:**
- **MUST-FIX:** 5 — F3.N-1 (toFixed test bug), F3.N-2 (900 m km regression), F3.N-3 (`/i` flag defeats `(?=[A-Z])` guard), F3.N-4 ("Then, " strip never matches Valhalla output + spec misrepresents baseline), F3.N-5 (30-m fixture test contradicts 100-ft cutoff), F3.N-13 (chain-append double-prefix exceeds pre-maneuver buffer)
- **SHOULD-FIX:** 3 — F3.N-6 (cutoff mismatch between metric constant and imperial branch), F3.N-7 (TTS `"1/4"` pronunciation untested), F3.N-8 (speech-time cannibalization understated ~40–70%)
- **LOW:** 8 — F3.N-9 (feet→miles transition), F3.N-10 (100-m boundary clarity), F3.N-11 (`2.0 kilometers` trailing zero + singular/plural), F3.N-12 (feet-band headline vs output range), F3.N-14 (band-boundary jitter), F3.N-15 (return-type contract), F3.N-16 (`_geographicaUseImperial` global coupling)

**Total:** 16 findings, 6 must-fix (one — F3.N-13 — overlaps with F3.N-8).

**Headline takeaway.** The §5 formatter has three independent numerical / regex bugs that would each fail the §5.5 tests on landing (F3.N-1, F3.N-3, F3.N-5). The spec's §9 speech-time estimate is low by 40–70%; after correction, the net buffer gain for the chain-append case at 25 mph is *negative*, meaning Issue 2 partially un-does Issue 1 on the exact field symptom. The 900 m → 0.9 km regression (F3.N-2) is a subtle but user-visible UX bug that surfaces on every metric-user drive crossing 900 m.

**Blocking questions for spec v2:**
1. Are `"1/4 mile"`-style strings acceptable for TTS, or should the spec switch to spelled-out fractions (`"In a quarter mile"`) to match Valhalla's own phrasing and avoid engine-dependent pronunciation?
2. Does chain-append keep a distance prefix on the trailing clause, or does it suppress to manage the speech-time budget?
3. Does Issue 1's floor need to lift further (to ~90 m) to cover the real +2.4 s speech cost of double-prefix chain-append utterances?
4. Is `toFixed` acceptable for km formatting, or should the spec mandate `Math.round(m/100)/10` to eliminate the `(0.95).toFixed(1) = "0.9"` class of bugs?
