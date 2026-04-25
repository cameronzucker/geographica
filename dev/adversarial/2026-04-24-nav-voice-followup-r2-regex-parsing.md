# Nav voice follow-up — R2 regex & Valhalla-parsing adversarial review

**Agent:** pinyon-sub-r2
**Date:** 2026-04-24
**Spec under review:** [2026-04-24-nav-voice-followup-design.md](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md) — §5.1 `stripBakedDistance`, §5.2 near-tier + chain-append recipes, §5.4 expected transcripts
**Attack angle:** Stress-test `BAKED_DISTANCE_RE` and the surrounding text-transform pipeline against the **live Valhalla** outputs on this Pi (query to `http://localhost:8093/valhalla/route`), with emphasis on real phrasing shapes the spec's vectors don't model.

Queries ran against live Valhalla on this Pi. Live response fixtures cached at `/tmp/valhalla_villa_rita.json`, `/tmp/valhalla_hwy.json`, `/tmp/valhalla_ped_metric.json`, `/tmp/valhalla_bike.json`, `/tmp/valhalla_truck.json`, `/tmp/valhalla_fr.json`.

---

### F2.1 — Regex is anchored at `^In` but Valhalla rarely emits distance at position 0

**Severity:** MUST-FIX

**Claim.** `BAKED_DISTANCE_RE = /^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|...)\s*,\s*(?=[A-Z])/i` only matches when the text **starts** with "In <dist> <unit>, ". Across every one of the 5 Valhalla responses I captured (auto/truck/bicycle/pedestrian/fr-FR over Phoenix-area routes), **no** `verbal_pre_transition_instruction` or `verbal_transition_alert_instruction` I observed begins with "In <distance>". The baked-distance pattern Valhalla actually emits is **embedded mid-string**, always following "Then,":

Observed shapes from live queries:

- `"Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue."` (Villa Rita depart, auto)
- `"Drive north on North Central Avenue. Then, in a quarter mile, Keep left to stay on North Central Avenue."` (Phoenix → Prescott, auto + truck)
- `"Turn left onto West Glendale Avenue. Then, in 300 feet, Make a sharp left to stay on West Glendale Avenue."` (Phoenix truck route)
- `"Drive east. Then, in 900 feet, Turn left onto North 21st Avenue."` (`verbal_succinct_transition_instruction` variant of the same)

`BAKED_DISTANCE_RE` **does not match any of these** because of the `^` anchor. Spec §5.1 asserts the regex covers Valhalla's "multi-cue depart" case (see §G8: "In 200 feet, In 900 feet, Turn left onto 21st Avenue"), but that constructed example is **not a real Valhalla emission**. The real emission is `"Drive east on ... . Then, in 900 feet, Turn left ..."`, which is a completely different shape.

Layered on top: the **existing** "Then" strip at [navigation.js:413](../../frontend/navigation.js#L413), `text.replace(/\.\s*Then\s+[^.]*\.?\s*$/i, '.')`, **also fails** on this shape — its `\s+` after `Then` requires whitespace, but Valhalla emits `Then,` (comma). Traced end-to-end:

```
INPUT:  'Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue.'
Step 1 (trailing-Then strip):  no match (Then is followed by ',', not \s+)
Step 2 (leading-Then strip):   no match (doesn't start with Then)
Step 3 (stripBakedDistance):   no match (^In anchor)
Step 4 (uppercase first):      unchanged
OUTPUT: 'Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue.'
```

**Impact.** G8 is unmet. On the canonical Villa Rita → Costco drive, the very first near-tier prompt (seg 0 → seg 1 at ≤ 65 m) fires with the full multi-cue text **and** the new live-distance prefix prepended — producing the exact nonsense the spec explicitly claimed to avoid: `"In 200 feet, drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue."` That prompt is ~7 s of TTS speech; at 25 mph surface-street speed, a 7-s prompt fired at 65 m (5.8 s to intersection) **completes 1.2 s AFTER the driver broaches the turn** — strictly worse than the pre-spec behavior.

**Recommendation.** Either

1. **Use the `verbal_transition_alert_instruction` / `verbal_succinct_transition_instruction` fallback chain instead of `verbal_pre_transition_instruction` for the depart maneuver**, since VTA for depart is typically shorter / doesn't carry the multi-cue; OR

2. **Broaden the strip to handle mid-string distance phrases** with a pattern that also strips `", Then, in <dist> <unit>, <Instruction>"` suffixes entirely (since the multi-cue is exactly the structure the spec wants to replace with a live prefix). Candidate:

   ```js
   // Strip trailing "Then, in <dist>, <Instr>" (replaces ALL of it — engine will prepend its own live prefix)
   text = text.replace(/\.\s*Then\s*,\s*in\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km|m)\s*,\s*[^.]*\.?\s*$/i, '.');
   ```

   AND fix the existing "Then" strip to accept `Then,`:

   ```js
   text = text.replace(/\.\s*Then\s*[,\s]\s*[^.]*\.?\s*$/i, '.');
   ```

Either path must be tested against the fixtures cached at `/tmp/valhalla_*.json` before shipping.

---

### F2.2 — The `/i` flag defeats the `(?=[A-Z])` "capital-letter" guard

**Severity:** MUST-FIX

**Claim.** Spec §5.1 explicitly relies on `(?=[A-Z])` as an **over-match guard**: "The `(?=[A-Z])` lookahead ensures we only strip when the residual starts with a capital — an additional guard that the stripped span was in fact a prefix, not the start of the instruction." Test vector claims `"In 400 feet, turn left."` (lowercase `t`) does NOT strip — **this is wrong**. Verified in V8 (node) with the spec's exact regex:

```
MATCH "In 400 feet, turn left." -> residual "turn left."
MATCH "In 400 feet, you will turn." -> residual "you will turn."
MATCH "In 400 feet, IKEA is on your right." -> residual "IKEA is on your right."
MATCH "In 400 feet, Turn left." -> residual "Turn left."
```

In JavaScript (and Python `re`), when the `i` flag is applied to a regex, `[A-Z]` matches any ASCII letter regardless of case. The lookahead `(?=[A-Z])` with `/i` is equivalent to `(?=[A-Za-z])` — the "capital" distinction is erased. The guard the spec relies on **does not exist**.

**Impact.** Two consequences:

1. The spec's own test vectors for `stripBakedDistance` at §5.5 are incorrect. Specifically `stripBakedDistance("In 400 feet, you will turn.") === "In 400 feet, you will turn."` (no-op assertion) will **fail** — the function strips to `"You will turn."` (after the downstream uppercase step). A TDD implementer would implement the regex as written, the negative test would fail, and whoever fixes it will either (a) weaken the test or (b) introduce a bug fixing the "guard" in a non-obvious way.
2. Any non-English-start-of-sentence residual is also stripped — which extends to any locale Valhalla outputs. F2.6 covers locale scope separately.

**Recommendation.** Choose one:

1. **Remove the `/i` flag** on the regex. The "In" prefix and unit words are always emitted in title case / lowercase by Valhalla, so case-insensitive match is cheap-to-lose. Drop `/i`; the `[a-zA-Z]` in the middle class handles the unit, and `[A-Z]` in the lookahead now actually enforces uppercase.
   ```js
   var BAKED_DISTANCE_RE = /^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km|m)\s*,\s*(?=[A-Z])/;
   ```
2. **Or** declare the guard unnecessary in spec text (Valhalla-emitted instructions always start with a capital, so the lookahead is redundant anyway). Update the test vectors in §5.5 to reflect what the regex actually does.

Either way, **update §5.1's narrative** ("lowercase `t` after comma — deliberate guard; won't strip") and §5.5's test vectors.

---

### F2.3 — Spec test vector `formatDistancePrefix(290, true) === "In 1000 feet, "` can't be true under stated rounding rule

**Severity:** SHOULD-FIX

**Claim.** Spec §5.5 asserts: `formatDistancePrefix(290, true) === "In 1000 feet, "` with the comment `(951.4 ft, still in feet band since < 1000 ft, rounds to 1000)`. This is inconsistent two ways:

1. 290 m × 3.28084 = 951.44 ft. Rounded to nearest 100 = 1000. OK.
2. But the band spec says `[100, 1000) ft: "In N00 feet, " (rounded to nearest 100)`. The half-open interval `[100, 1000)` **excludes** 1000 exactly. If the rounding bumps 951.4 → 1000, the output now escapes the feet band. The spec's note tries to accommodate this ("feet-band's output can legitimately say '1000 feet'"), but this contradicts the adjacent band `[1000, 5/16 mi) ft: "In 1/4 mile, "`, which claims 1000 ft through 1650 ft should be expressed as "1/4 mile".

The deterministic collision point: `formatDistancePrefix(305, true)` (1000.66 ft = 0.1895 mi) is asserted to be `"In 1/4 mile, "`, while `formatDistancePrefix(290, true)` (951.4 ft) is `"In 1000 feet, "`. So a **1-meter drop** (290→305 is actually a 15-meter increase, but the band boundary itself is at some `d_boundary` where `d × 3.28084 = 1000` → `d = 304.8 m`) swings from "1000 feet" to "1/4 mile" on live ticks.

**Impact.** Dual presentation of the same distance across nearby GPS ticks. At 25 mph the driver hears "In 1000 feet, turn right" and 2 s later "In 1/4 mile, turn right" — it *sounds* like the second prompt went backwards (1/4 mile = 1320 ft > 1000 ft). This is a UX regression the spec intends to prevent.

**Recommendation.** Decide one of:

1. Tighten the feet-band upper to `< 950 ft` (or equivalently round-up threshold `< 290 m`). Values 290 m–305 m always cross the band boundary and produce "1/4 mile" from one tick onward. Spec should reassert that in §5.1 and update the §5.5 test vector to `formatDistancePrefix(290, true) === "In 1/4 mile, "` (since 951.4 ft / 5280 = 0.1802 mi, rounded to nearest 1/4 = 0.25, output "In 1/4 mile, ").
2. Keep the spec as written but add an invariant: `formatDistancePrefix(m1) ≤ formatDistancePrefix(m2)` (monotone in meters) and enforce it with a property-style test. If the spec's band definitions don't satisfy monotonicity, this finding forces the author to collapse the feet-band ceiling below the rounding-up point.

---

### F2.4 — Regex over-matches embedded hedges ("In about...", "In approximately...") with no guard

**Severity:** SHOULD-FIX

**Claim.** The spec acknowledges this open question in §9 ("are there Valhalla output shapes not covered... e.g., 'In about half a mile'?"), but the regex as written **does** strip these — in fact it strips **any** word-sequence between "In" and the unit, because `[a-zA-Z0-9.\s]+?` is too permissive. Verified against the regex:

```
MATCH "In about half a mile, Turn right." -> residual "Turn right."        (OK — strips cleanly)
MATCH "In approximately 500 meters, Turn." -> residual "Turn."             (OK)
MATCH "In less than 100 feet, Turn." -> residual "Turn."                   (OK)
MATCH "In 2 tenths of a mile, Turn." -> residual "Turn."                   (OK)
MATCH "In three quarters of a mile, Turn." -> residual "Turn."             (OK)
```

Good news: all these hypotheticals **DO** strip. Bad news: this happens for reasons that make the regex dangerous. `[a-zA-Z0-9.\s]+?` will **greedily enough** consume anything up to the first `\s<unit>\s*,` terminator. So if Valhalla ever emits `"In 400 feet, after the stop sign, Turn left."` (not observed in my queries, but Valhalla has known multi-clause verbalizations), the regex greedily matches `In 400 feet, after the stop sign` as the prefix span? Let's check: no, because `[^.]*` is in the Then-strip, not here. The `stripBakedDistance` regex **requires** `\s<unit>\s*,\s*` — so it stops at the first unit-comma boundary. Safe here.

But there's a narrower concern: `"In 400 feet, Merge, Stay on I-5."` matches and yields residual `"Merge, Stay on I-5."` (OK — residual is natural). And `"In 400 feet,\nTurn left."` (with embedded newline) matches because JS `\s` includes `\n`. Also OK.

Where it **does** go wrong: the class `[a-zA-Z0-9.\s]+?` **matches the literal distance unit embedded mid-phrase**. Example: `"In 500 m, Turn."` — the spec allows `m` as a unit. The regex non-greedy engine finds the shortest successful span, which means it can match `In 500 m, ` (distance=500, unit=m, residual="Turn.") — fine. But if Valhalla ever says `"In a m block, Turn."` the regex eats it too. Not realistic, but note the unit `m` alone is a minefield. The spec's existing unit list includes `m` explicitly, which exists to support metric 5m / 10m notation — **but I did not observe a single Valhalla response where the unit was the bare letter `m`**. Valhalla emits `"meters"` (plural full word) exclusively.

**Impact.** Low in practice, but the `m` unit alone creates a regex footgun for future maintenance (imagine an engineer adds a new Valhalla v2 tag that includes a trailing `, m,` for reasons).

**Recommendation.** Drop `m` from the unit alternation. Keep `km` (common abbreviation). If Valhalla ever needs `m` support in the future, add it back with a surrounding `\b` anchor to prevent partial-word matches. Revised:

```js
var BAKED_DISTANCE_RE = /^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km)\s*,\s*(?=[A-Z])/;
```

---

### F2.5 — Spec §5.1 example "In 200 feet, In 900 feet, Turn left..." is not a real Valhalla emission

**Severity:** NICE-TO-HAVE (documentation fidelity)

**Claim.** Spec §4 (Issue 1 summary) and G8 reference the doubled-prefix scenario: `"In 200 feet, In 900 feet, Turn left onto 21st Avenue."` as the failure mode that `stripBakedDistance` prevents. Scanned all live Valhalla responses (auto, truck, bicycle, pedestrian, en-US + fr-FR): **no instruction string begins with "In <dist>"**. The actual baked-distance-containing shape is `"<Verb phrase>. Then, in <dist>, <Imperative>."` — which the spec's regex does not match (see F2.1).

**Impact.** The motivating example in the spec is fictional. Reviewers and future maintainers believe the regex solves a problem that, in the form described, does not occur in real traffic. The REAL problem (F2.1) is different and goes unaddressed.

**Recommendation.** Rewrite §4/G8 using the actual observed shape: *"Valhalla's `verbal_pre_transition_instruction` on depart/continuation maneuvers bakes a secondary cue after the current instruction: `"Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue."` Without stripping, the engine would prepend a live prefix to produce `"In 200 feet, Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue."` — two distances in the same utterance, confusing the driver."* Then align the regex to strip the actual shape (F2.1 recommendation).

---

### F2.6 — No explicit English-only scope declaration; locale drift would silently break the strip

**Severity:** NICE-TO-HAVE

**Claim.** Frontend never passes `language` in `directions_options` ([nav-ui.js:534](../../frontend/nav-ui.js#L534), [app.js:2090](../../frontend/app.js#L2090)), so Valhalla defaults to en-US — confirmed by `"language":"en-US"` in every response. I queried Valhalla with `language=fr-FR` to verify French output uses a completely different shape: `"Conduisez vers l'est sur West Villa Rita Drive. Ensuite, dans 900 pieds, Tournez à gauche dans North 21st Avenue."` The baked-distance phrase is `"dans 900 pieds,"` — neither `stripBakedDistance`'s regex ("In ... feet") nor `formatDistancePrefix`'s output (literal English) has any hope of working.

**Impact.** Zero today (no code path sets `language`). Non-zero if a future PR exposes a locale picker. When that happens, the regex silently no-ops (no strip → double prefix) and `formatDistancePrefix` emits English into a non-English TTS stream ("In 200 feet, Tournez à gauche..."). A user who thinks they're testing a French language picker gets a mixed-language prompt that's never intercepted.

**Recommendation.** Add one paragraph to §5.1 declaring the feature **English-only**, with a reference to where locale expansion would hook in:

> **Locale scope.** `BAKED_DISTANCE_RE` and `formatDistancePrefix` both assume English (en-US) Valhalla output. This matches the current frontend, which does not pass `directions_options.language` and relies on Valhalla's en-US default. If a future locale picker is introduced, both helpers must be locale-aware (regex variant per language, unit names from an i18n table). Until then, the feature is guarded by the "English assumed" invariant — I15.

And optionally an assertion in code:

```js
if (route.language && !/^en/i.test(route.language)) {
  // Skip distance-prefix and strip — English-only.
  return text;
}
```

---

### F2.7 — `verbal_succinct_transition_instruction` is the primary emission on Pi's Valhalla build — the spec never reads it

**Severity:** SHOULD-FIX

**Claim.** Every maneuver in every live response I captured includes `verbal_succinct_transition_instruction` ("Turn left.", "Bear right.", "Drive east. Then, in 900 feet, Turn left onto North 21st Avenue."). It is shorter and faster to speak. But the spec at §5.2 hardcodes the fallback chain `m.verbal_pre_transition_instruction || m.instruction || ""` and §5.2's far-tier `m.verbal_transition_alert_instruction || m.instruction || ""`. **Neither path ever consults `verbal_succinct_transition_instruction`**.

Cross-reference the TTM v3 spec's open questions at [2026-04-20-nav-voice-ttm-design.md](../../docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md): "succinct vs pre-transition text" was called out as a latent design choice. Follow-up spec v1 retains the v3 choice of `verbal_pre_transition_instruction`. The implication is:

- With the new prefix, near-tier utterance length compounds:
  - Current: `"Turn left onto North 21st Avenue."` (5 words, ≈ 1.5 s speech)
  - v3 + prefix: `"In 200 feet, turn left onto North 21st Avenue."` (9 words, ≈ 2.6 s)
  - v3 + prefix on depart (if F2.1 unfixed): `"In 200 feet, Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue."` (~22 words, ≈ 6.5 s)

Using `verbal_succinct_transition_instruction` for near-tier would reverse compound bloat: `"Drive east. Then, in 900 feet, Turn left onto North 21st Avenue."` (13 words). Still long, but ~40% shorter.

**Impact.** Cross-issue — the spec itself flags in §9 that the prefix adds speech time that eats into the +1.3 s buffer Issue 1 bought. If near-tier text is as long as an unpruned depart-vpt, the post-speech buffer goes NEGATIVE at 25 mph. Review this before merging.

**Recommendation.** Explicit decision in the spec: either

1. Add §5.2.bis "text-source selection" — prefer `verbal_succinct_transition_instruction` for near-tier when it's shorter than `verbal_pre_transition_instruction`, fall back otherwise. Accept the complexity for shorter TTS.
2. Document why `verbal_pre_transition_instruction` remains the choice (richness > speed), and add a corresponding invariant that near-tier TTS always completes before the intersection even at 25 mph WITH the new prefix. Field-test this explicitly on the Villa Rita → Costco regression route — the spec's §7 acceptance criteria do not cover speech-duration regression.

---

### F2.8 — Chain-append strip on `route.maneuvers[afterIdx].instruction` is dead defensive code

**Severity:** NICE-TO-HAVE

**Claim.** Spec §5.2 applies `stripBakedDistance(route.maneuvers[afterIdx].instruction || "")`. I scanned all maneuvers across all 5 live Valhalla responses (auto, truck, bicycle, pedestrian, fr-FR): **zero** `.instruction` fields begin with "In " — across every costing and every locale I tested, Valhalla's `.instruction` is always the bare imperative ("Turn left onto X.", "Drive north on Y."). The strip is purely defensive.

**Impact.** None — the code is correct, just cost-free. Worth calling out so maintainers don't assume the strip is load-bearing for a currently-occurring phenomenon. If someone later "optimizes" by removing it, the removal is safe against observed Valhalla behavior. If someone later changes `afterText` to read `verbal_pre_transition_instruction` (which DOES sometimes bake distance in multi-cue form), the strip becomes critical.

**Recommendation.** Either

1. Keep the strip but add a comment: *"Defensive — Valhalla's `.instruction` field is not observed to contain distance prefixes as of 2026-04. If this is ever changed to read `verbal_pre_transition_instruction`, the strip becomes load-bearing against multi-cue depart shapes."* OR
2. Remove the strip and document it. Removal is safe per current observations.

---

### F2.9 — Regex permits zero-digit "distance" like `"In a mile, Turn."` — and strips correctly, but spec §5.1 doesn't confirm

**Severity:** NICE-TO-HAVE

**Claim.** Observed shapes include `"Continue for a quarter mile."` and `"in a quarter mile,"` — fraction-word forms. The spec lists `"In a quarter mile, Turn left."` as a match vector. I verified the regex correctly handles the full grammar family on the node runtime:

```
MATCH "In a quarter mile, Turn left." -> residual "Turn left."
MATCH "In half a mile, Turn." -> residual "Turn."
MATCH "In a half mile, Turn." -> residual "Turn."
MATCH "In 1.5 miles, Merge onto I-5." -> residual "Merge onto I-5."
MATCH "In 500 meters, Turn." -> residual "Turn."
MATCH "In about half a mile, Turn right." -> residual "Turn right."
MATCH "In 0.75 miles, Turn." -> residual "Turn."
MATCH "In a mile, Turn." -> residual "Turn."          <- degenerate but works
MATCH "In 500 m, Turn." -> residual "Turn."
MATCH "In aaaaa...100-a's... feet, Turn." -> strips   <- possible ReDoS vector, mitigated by non-greedy + anchored ^
NOMATCH "In -5 feet, Turn."                            <- negative numbers rejected (OK)
NOMATCH "In miles, Turn."                              <- no quantity rejected (OK)
NOMATCH "In  , Turn."                                  <- empty quantity rejected (OK)
```

No ReDoS risk because the regex is anchored `^` and the `+?` is non-greedy.

**Impact.** Nominal — spec's claims for match/non-match are correct for these vectors. One gap: spec §5.1 test vectors don't explicitly include `"In half a mile"` (order reversed vs "a half mile"). Both match, but the spec should name the vectors it expects to cover.

**Recommendation.** Add to §5.5 test list:

```js
stripBakedDistance("In half a mile, Turn.") === "Turn."   // "half a mile" form
stripBakedDistance("In a half mile, Turn.") === "Turn."   // "a half mile" form (currently listed)
stripBakedDistance("In 0.75 miles, Turn.") === "Turn."    // decimal form
stripBakedDistance("In 500 m, Turn.") === "Turn."         // bare-m unit (or remove per F2.4 rec)
```

---

## Summary

| Severity | Count |
|---|---|
| MUST-FIX | 2 (F2.1, F2.2) |
| SHOULD-FIX | 3 (F2.3, F2.4, F2.7) |
| NICE-TO-HAVE | 4 (F2.5, F2.6, F2.8, F2.9) |
| **Total** | **9** |

**Headlines:**

- **F2.1** and **F2.2** are both ship-blockers. F2.1 invalidates G8: the spec's regex was built against a constructed straw-man shape (`"In 200 feet, In 900 feet, Turn ..."`) that Valhalla **never emits**; the real shape (`"<verb phrase>. Then, in 900 feet, <Imperative>."`) goes un-stripped, producing a compound prompt that is **strictly worse than baseline** at the symptom speed. F2.2 is a latent code correctness bug: the `(?=[A-Z])` "guard" is not a guard because `/i` makes the character class case-insensitive — the spec's own test vectors for the negative case are wrong.
- **F2.3** is a monotonicity bug: the spec's band definition lets `formatDistancePrefix(290) = "In 1000 feet, "` followed by `formatDistancePrefix(305) = "In 1/4 mile, "` — distance grows but the spoken value goes 1000 → 1320 ft. Drivers will hear the prompt rewind.
- **F2.4** and **F2.7** are UX/maintenance concerns: the bare `m` unit is a footgun, and routing near-tier to `verbal_pre_transition_instruction` instead of `verbal_succinct_transition_instruction` compounds prefix-bloat into unshipable prompt lengths on depart maneuvers.
- **F2.5**, **F2.6**, **F2.8**, **F2.9** are documentation and hygiene.

Before writing-plans runs on v2: rework §5.1's regex to handle the real Valhalla emission shape (mid-string `Then, in <dist>, <Instr>`), drop the `/i` flag or the meaningless guard, and fix the monotonicity/test-vector bugs in §5.5.
