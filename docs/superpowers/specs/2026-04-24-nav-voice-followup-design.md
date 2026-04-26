# Nav voice TTM follow-up — low-speed floor lift + live-distance prefix

**Date:** 2026-04-24
**Agent:** pinyon
**Scope:** Two surgical changes to `frontend/navigation.js` for field-surfaced issues post-TTM-ship: (1) raise the near-tier distance floor to give surface-street drivers ~+1 s of post-speech buffer; (2) add a Google-Maps-style live-distance prefix to far-tier, near-tier, and chain-append prompts so eyes-free drivers can disambiguate "this turn vs the next intersection." Issue 3 (sidebar BFCache restore) was originally in this spec; **split out** to [2026-04-24-sidebar-tab-restore-design.md](2026-04-24-sidebar-tab-restore-design.md) per adversarial review F5.1 / F4.13 — different file, different test harness, different risk surface.
**Files:** [frontend/navigation.js](../../../frontend/navigation.js) (primary), [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs) (tests).
**Prior art:**
- [2026-04-20-nav-voice-ttm-design.md](2026-04-20-nav-voice-ttm-design.md) — TTM v3 spec (the baseline this amends)
- [2026-04-21-nav-voice-picker-design.md](2026-04-21-nav-voice-picker-design.md) — voice picker (orthogonal; preserves the `onVoiceCb` boundary this amends)

## Revision history

- **v3 (2026-04-25)** — Field-test from Cameron (Villa Rita → 24th drive) surfaced B1: every auto floor-triggered near-tier fire produced "In 200 feet" deterministically because `VOICE_DISTANCE_FLOOR.auto = 75m` × 3.28084 = 246 ft maps to the "200 feet" bucket. Strategy B fix lands: distinguish TTM-fire (prefix applied) from floor-fire (bare maneuver text, chain prefix preserved). The 30 m / 100 ft cutoff intent ("read as imminent below this") is now re-grounded via fire-mode rather than the never-reachable distance threshold. Floor values unchanged; Issue 1 buffer preserved. See [bug-hunt](../../dev/bug-hunts/2026-04-24-nav-distance-post-m1-consolidated.md) and [plan](../../dev/plans/2026-04-25-nav-distance-floor-fire-suppression-plan.md).
- **v2 (2026-04-24)** — Substantial rewrite after 5-round adversarial review (4× Claude lenses + 1× Codex cross-validation). Findings live at [dev/adversarial/2026-04-24-nav-voice-followup-r{1..5}-*.md](../../../dev/adversarial/). 8 MUST-FIX, 18 SHOULD-FIX (deduped) addressed:
  - **Floor raised 65 → 75 m** (auto), 40 → 45 m (bicycle). Original 65 m left slow-voice users net-worse-than-baseline once prefix TTS was accounted for (R4 F4.1, R3 F3.N-8, R1 F1.3). 75 m holds positive buffer for slow voices; Cameron's call ("we can adjust later in testing"), prioritizing pragmatic deployability over over-fitting.
  - **`stripBakedDistance` regex fundamentally rewritten.** Original `^In <dist> <unit>,` anchor never matched real Valhalla emissions, which use mid-string `". Then, in <dist>, <Imperative>"` form (R2 F2.1, R3 F3.N-4). New regex strips the trailing `". Then, in <dist>, <rest>"` chain entirely (since the new live-prefix replaces it). Also fixes the existing `". Then "` strip to accept `". Then, "` (comma form), which was a pre-existing latent bug.
  - **`/i` flag dropped.** Combined with `(?=[A-Z])` lookahead it was meaningless — `[A-Z]` becomes case-insensitive under `/i` (R2 F2.2, R3 F3.N-3). Valhalla always emits title-case so `/i` was unnecessary.
  - **Spelled-out fractions** instead of `"1/4 mile"` literal. Matches Valhalla's own phrasing ("a quarter mile"), pronounces deterministically across TTS engines (R3 F3.N-7), reads more naturally. Bands collapse from 5 fractional steps to 4 (1/4, 1/2, 3/4, 1) — drop the 1/3 band that no real navigation app uses.
  - **Metric band redrawn.** Spec'd `>= 900 m → "In 0.9 kilometers"` was a real regression — value drops 1000× across a 1 m boundary (R3 F3.N-2). New: meters band extends to 999 m, switch to "In one kilometer" at 1000 m (no fractional km below 1.0).
  - **`(0.95).toFixed(1) === "0.9"` test-vector trap removed** (R3 F3.N-1) — explicit `Math.round(meters/100)/10` for km, no `.toFixed`.
  - **GPS-recovery guard added** (Codex F5.4): on the first tick after `drActive` ends or `gpsStale` clears, the prefix is suppressed for that tick. Prompt fires with maneuver text only ("Turn left onto X"), not a jarringly-precise "In 200 feet, turn left onto X" computed from a single recovered GPS sample.
  - **Issue 3 split out** (Codex F5.1, R4 F4.13): see separate spec.
  - **§5.4 Villa Rita transcripts re-derived** from live Valhalla output (per R2 F2.1's correction that the v1 transcripts were partly fictional). All distances and prefixes re-checked against the actual `/valhalla/route` response.
  - **Same-maneuver far/near with two different distance prefixes accepted** as standard escalation UX (Codex F5.3 noted but deferred). Cameron: "second prompt as escalation, not correction" — matches Google Maps behavior; only revisit if field-tested as confusing.
  - **Reject `verbal_succinct_transition_instruction` substitution** (R2 F2.7): succinct drops the street name (`"Turn left."` vs `"Turn left onto North 21st Avenue."`), which destroys the disambiguation case that motivates Issue 2 in the first place. Stay on `verbal_pre_transition_instruction`.
  - **Empty-text + announcedSet exception-safety** (R1 F1.1, F1.2): mark `announcedSet` BEFORE the prefix-text construction so an exception in `formatDistancePrefix` doesn't leave the maneuver in a "fired but mute" state.
  - **Dead chain-append strip kept** (R1 F2.8 NICE-TO-HAVE): comment marks it as defensive in case a future change reads `verbal_pre_transition_instruction` for the chain.
- **v1 (2026-04-24, commit `4321de7`)** — Initial design covering Issues 1+2+3 in a single spec. Bundled per delivery cohesion, but adversarial review surfaced that the bundling muddies risk analysis and the v1 design has 8 MUST-FIX issues (regex doesn't match real output; floor lift doesn't survive prefix TTS; sidebar fix is narrower than claimed). Replaced by v2.

## 1. Summary

Two field-surfaced defects on the live dev stack post-TTM-ship:

1. **Near-tier fires too close at surface speeds.** The 50 m floor at [navigation.js:53](../../../frontend/navigation.js#L53) governs whenever `3 × speed < 50` (i.e., speeds below ~37 mph). At 25 mph the prompt fires 4.5 s before the intersection; after ~3 s of TTS speech plus ~0.5 s network/init latency, the driver has effectively 0 s of post-speech buffer. **Fix:** raise the floor (auto 50 → 75 m, bicycle 30 → 45 m). At 25 mph that's 6.7 s of warning, leaving ~1.6 s of post-speech buffer even when the prefix is added (Issue 2) and even on slow TTS voices (eSpeak, iOS Daniel). High-speed (≥37 mph) timing is unchanged because TTM still governs.

2. **Prompts lack distance context.** Valhalla's `verbal_transition_alert_instruction` for most turns is the bare turn ("Turn left onto West Utopia Road.") with no distance. The far-tier fires at 486 m on Union Hills (36 mph), but the spoken text says nothing about distance. The near-tier's chain-append (", then turn left onto Utopia Road") also carries no distance ever. An eyes-free driver can't disambiguate "is this turn imminent or a third of a mile out?" — the disambiguation case Cameron flagged. **Fix:** compute the live distance from the TTM snapshot already in hand (`distToNext` for the current maneuver, `distBetween` for the chain-append), strip any baked-in distance Valhalla bakes into the source text (mid-string "Then, in <dist>" form), format by user unit preference (spelled-out fractions in imperial; meters/kilometers in metric), prepend.

## 2. Goals & non-goals

### Goals

- **G1.** At 25 mph (the field-symptom speed), the near-tier fires ≥ 1 s earlier than current (50 → 75 m absolute distance change). With the 75 m floor governing, the floor itself provides the timing improvement; the absolute change is independent of speed within the floor-governed regime.
- **G2.** Even with Issue 2's prefix added (~0.7 s extra TTS for fast voices, ~1.5 s for slow voices), post-speech buffer at 25 mph remains positive across the full voice-picker matrix. Slow-voice scenario: 75 m / 11.2 m/s = 6.7 s warning − 5 s slow-voice TTS − 0.5 s init = 1.2 s buffer.
- **G3.** TTM-governed timing (≥ 37 mph speeds) is bit-identical to pre-fix for Issue 1. The floor is inactive whenever `3 × speed ≥ floor`.
- **G4.** Stationary-driver invariants from TTM v3 (I3, I4) preserved with the new floor values. I3: zero announcements when stationary > floor. I4: near-tier fires when stationary ≤ floor.
- **G5.** Every voice prompt fired by `checkVoice` carries a live-distance prefix unless distance < 30 m / 100 ft cutoff (imminent-turn semantics). Same prefix logic for far-tier, near-tier, and chain-append — same disambiguation across all tiers.
- **G6.** Chain-append carries its own distance prefix measured from current maneuver to next-after-next.
- **G7.** Format follows `useImperial`. Imperial: feet (rounded 100) up to 999 ft, then "In a quarter mile" / "In half a mile" / "In three quarters of a mile" / "In one mile", then "In N miles" (Math.round, smallest output is 2). Metric: meters (rounded 10 below 100 m, rounded 50 from 100-999 m), then "In one kilometer" at 1000 m, then "In N kilometers" (1-decimal rounded, smallest 1.5 from band lift).
- **G8.** When Valhalla bakes a distance into the source text via the multi-cue mechanism (mid-string ". Then, in <dist>, <Imperative>" form), the trailing chain is stripped before the live-distance prefix is prepended. Single distance announcement per prompt — no "In 200 feet, drive east on X. Then, in 900 feet, Turn left onto Y" doubling.
- **G9.** Prompt count, ordering, and chain-eligibility logic UNCHANGED. Issue 2 is a presentation-layer transform; counts must be invariant on the canonical Villa Rita → Costco trace (verified 11 prompts in §5.4).
- **G10.** GPS-recovery guard (Codex F5.4): on the first tick after `drActive` clears OR after `gpsStale` clears (whichever comes first), the prefix is suppressed for that tick — prompt fires with maneuver text only. Prevents jarringly-precise "In 200 feet" computed from a single recovered GPS sample after dead-reckoning estimation.
- **G11.** `announcedSet` mutation order is exception-safe. Marks happen BEFORE prefix construction, so a thrown exception in `formatDistancePrefix` or `stripBakedDistance` doesn't permanently mute a maneuver. The cost of this ordering is that an exception leaves the maneuver "marked but never spoken" — better than "mute forever."
- **G12.** Villa Rita → Costco field drive (canonical TTM regression route) still produces 11 prompts in the same order. Timing shifts (Issue 1) and text content changes (Issue 2) are the only observable deltas.

### Non-goals

- **NG1.** No change to `VOICE_TTM` tier thresholds (`[30, 3]` auto / `[20, 3]` bicycle / `[15, 2]` pedestrian). Only the floor.
- **NG2.** No change to pedestrian profile floor (stays 15 m). Walking-pace scenarios have ample buffer; field evidence absent.
- **NG3.** No change to `NEXT_AFTER_NEXT_DISTANCE = 500 m` chain-eligibility.
- **NG4.** No introduction of TTS-aware semantics (measured speech duration, mid-utterance suppression). Out of scope.
- **NG5.** No changes to `frontend/nav-ui.js`, `frontend/app.js`, `frontend/index.html`, or CSS. The `onVoiceCb(text)` boundary is preserved.
- **NG6.** No change to Valhalla routing. We consume route output as-is.
- **NG7.** No retroactive amendment of TTM v3 invariants I1–I11. I3 and I4's floor references resolve to 75/45/15 (was 50/30/15); shapes unchanged.
- **NG8.** No use of `verbal_succinct_transition_instruction` for the near-tier base text. Succinct drops street names ("Turn left.") which destroys the disambiguation case (Cameron's stated motivation). Stay on `verbal_pre_transition_instruction`.
- **NG9.** No second-tier "imminent" form for the near-tier when the same maneuver's far-tier already fired (Codex F5.3 deferred). Standard escalation UX matches Google Maps; revisit only if field-tested as confusing.
- **NG10.** No locale support beyond en-US. Frontend never passes `directions_options.language` ([nav-ui.js:534](../../../frontend/nav-ui.js#L534)) so Valhalla defaults to en-US. Future locale picker would require a re-design of both helpers (R2 F2.6).
- **NG11.** No changes to depart-maneuver speech (`maneuvers[0]`'s `verbal_pre_transition_instruction`). The depart text is never read by `checkVoice` (which advances `nextIdx = currentManeuverIdx + 1` past it). The multi-cue text on depart is spoken by a different mechanism (or not at all in the current engine); out of scope here.

## 3. Architecture

```
                                                         
   GPS service       │  updateGPS(data)      │  onVoiceCb(text)
   (services/gps)    │  ──────────────▶      │  ──────────────▶
                     │                       │
                     │  ┌─────────────────┐  │
                     │  │ navigation.js   │  │
                     │  │                 │  │
                     │  │  pushSpeedSamp  │  │
                     │  │  snapToRoute    │  │
                     │  │  checkVoice ────┼──┼────▶ onVoiceCb
                     │  │   ├─ NEW: GPS-  │  │       │
                     │  │   │   recovery  │  │       │
                     │  │   │   guard     │  │       │
                     │  │   ├─ stripBaked │  │       │
                     │  │   │   Distance  │  │       │
                     │  │   ├─ mark       │  │       │
                     │  │   │   announced │  │       │
                     │  │   │   Set       │  │       │
                     │  │   ├─ formatDist │  │       │
                     │  │   │   Prefix    │  │       │
                     │  │   └─ prepend +  │  │       │
                     │  │       fire      │  │       │
                     │  │                 │  │       │
                     │  │  drActive       │  │       │
                     │  │  recoveryFlag   │  │       │
                     │  │   (one-shot)    │  │       │
                     │  └─────────────────┘  │
                                                         
```

Pure in-engine change. External boundary preserved: voice-picker still consumes `onVoiceCb(text)`; nav-ui still speaks via SpeechSynthesis with selected voice.

## 4. Issue 1 — near-tier floor lift

### 4.1 Constants

Current at [navigation.js:52-56](../../../frontend/navigation.js#L52-L56):

```js
var VOICE_DISTANCE_FLOOR = {
  auto:       50,
  bicycle:    30,
  pedestrian: 15
};
```

New:

```js
var VOICE_DISTANCE_FLOOR = {
  auto:       75,  // +25 m. ~+2.2 s warning at 25 mph after Issue-2 prefix TTS.
  bicycle:    45,  // +15 m. Mirror scaling — 50% lift, same as auto's 50→75 ratio.
  pedestrian: 15   // unchanged. Walking-pace buffer ample.
};
```

### 4.2 Buffer math (auto, with Issue-2 prefix)

Effective TTS time at the symptom speed includes the prefix. Speech rates: fast-voice (Samantha) ≈ 2.5 wps; slow-voice (eSpeak / iOS Daniel) ≈ 1.8 wps. Init latency ~0.5 s.

| speed | fire dist (75 m floor) | warning time | sample utterance | TTS fast | TTS slow | buffer fast | buffer slow |
|---|---|---|---|---|---|---|---|
| 15 mph / 6.7 m/s | 75 m | 11.2 s | "In 200 feet, turn left onto X" (9 words) | 3.6+0.5 = 4.1 s | 5.0+0.5 = 5.5 s | 7.1 s | 5.7 s |
| 20 mph / 8.9 m/s | 75 m | 8.4 s | same | 4.1 s | 5.5 s | 4.3 s | 2.9 s |
| **25 mph / 11.2 m/s** | **75 m** | **6.7 s** | same | 4.1 s | 5.5 s | **2.6 s** | **1.2 s** |
| 30 mph / 13.4 m/s | 75 m | 5.6 s | same | 4.1 s | 5.5 s | 1.5 s | 0.1 s |
| 35 mph / 15.6 m/s | 75 m | 4.8 s | same | 4.1 s | 5.5 s | 0.7 s | -0.7 s ⚠ |
| 37 mph / 16.7 m/s | 75 m (boundary) | 4.5 s | same | 4.1 s | 5.5 s | 0.4 s | -1.0 s ⚠ |
| ≥48 mph (TTM regime) | `3 × speed` | 3.0 s | same | 4.1 s | 5.5 s | -1.1 s ⚠ | -2.5 s ⚠ |

**Key observations:**

- Surface streets (15-30 mph) hold a positive buffer even at slow voice. **The symptom speed (25 mph) gets +1.2 s slow-voice buffer** — material improvement vs current ~0 s.
- Above ~30 mph at slow voice the buffer goes negative — but this matches the **pre-existing** TTM v3 behavior at high speeds. The current TTM model's "3 s near tier" was always a "fires-3 s-out" not "completes-3 s-out" semantic. This spec doesn't fix that (out of scope per NG1); the floor lift only addresses the floor-governed regime where Cameron's symptom landed.
- **Negative buffer at high speed is pre-existing**, not introduced by this spec. R4 F4.1 flagged this risk; we accept it as out of scope and document it.

### 4.3 Invariant amendments

- **I3** (preserved shape, new value): zero announcements when stationary > 75 m / 45 m / 15 m.
- **I4** (preserved shape, new value): near-tier fires when stationary ≤ floor.
- **I12 (new)**: floor lift 50 → 75 m preserves exactly-2-prompts-per-maneuver invariant (TTM v3 G1) when entering from outside far-tier. Floor only governs near-tier; far-tier is TTM-only and floor-independent.

### 4.4 Tests

Add to `frontend/tests/engine/navigation.test.mjs`:

- `TTM I12: floor 75 auto fires near-tier at 75 m at 11.2 m/s` — parameterize existing floor-governs test over new value.
- `TTM I12: floor 45 bicycle fires near-tier at 45 m at 5 m/s`.
- `TTM I12: floor change does not affect prompt count on Villa Rita synthetic fixture` (G9 regression guard) — run `fixtureVillaRitaCluster`, assert count unchanged.
- `TTM I12: floor change does not affect mixed-spacing cluster prompt count` — run `fixtureMixedSpacingCluster`, assert count unchanged.
- Existing `TTM G1: fires exactly 2 prompts per maneuver at highway speed` continues to pass (TTM regime is floor-independent).

## 5. Issue 2 — live-distance prefix

### 5.1 New helpers

Both helpers live in `navigation.js` as module-private functions, exported via `_geographicaNavEngineInternals` for test access.

```js
// Small-distance cutoff — below this, prompts read as imminent.
var DISTANCE_PREFIX_CUTOFF_METERS = 30; // ≈ 100 ft

/**
 * Format a live distance in meters as a Google-Maps-style prefix.
 * Returns "" if below cutoff (caller speaks the maneuver alone).
 *
 * Imperial (useImperial=true):
 *   <100 ft: ""
 *   [100, 999] ft: "In N00 feet, " (Math.round(feet/100)*100)
 *   [1000, 1980) ft: "In a quarter mile, "          (~ 1320 ft midpoint)
 *   [1980, 3300) ft: "In half a mile, "             (~ 2640 ft midpoint)
 *   [3300, 4620) ft: "In three quarters of a mile, " (~ 3960 ft midpoint)
 *   [4620, 7920) ft: "In one mile, "                (~ 5280 ft midpoint)
 *   >= 7920 ft: "In N miles, " (Math.round(miles); smallest possible N is 2)
 *
 * Metric (useImperial=false):
 *   <30 m: ""
 *   [30, 99] m: "In N0 meters, " (Math.round(m/10)*10)
 *   [100, 999] m: "In NN0 meters, " (Math.round(m/50)*50)
 *   [1000, 1499] m: "In one kilometer, "
 *   >= 1500 m: "In N.N kilometers, " (Math.round(m/100)/10; smallest output is 1.5)
 *
 * NOTE on band boundaries: rounding can push a value into the next band's
 * absolute range, but bands are checked BEFORE rounding (band classification
 * uses the raw meters value, not the rounded output). E.g., 290 m = 951 ft is
 * in [100, 999] band → rounds to 1000 → output "In 1000 feet, ". 305 m = 1001 ft
 * is in [1000, 1980) band → "In a quarter mile, ". The "1000 feet" output is
 * a deliberate edge-case label (driver hears it for the upper few meters of
 * the feet band before crossing to fractional miles).
 */
function formatDistancePrefix(meters, useImperial) {
  if (meters < DISTANCE_PREFIX_CUTOFF_METERS) return "";
  if (useImperial) {
    var feet = meters * 3.28084;
    if (feet < 1000) return "In " + (Math.round(feet / 100) * 100) + " feet, ";
    var miles = feet / 5280;
    if (miles < 1980/5280) return "In a quarter mile, ";
    if (miles < 3300/5280) return "In half a mile, ";
    if (miles < 4620/5280) return "In three quarters of a mile, ";
    if (miles < 7920/5280) return "In one mile, ";
    return "In " + Math.round(miles) + " miles, ";
  } else {
    if (meters < 100) return "In " + (Math.round(meters / 10) * 10) + " meters, ";
    if (meters < 1000) return "In " + (Math.round(meters / 50) * 50) + " meters, ";
    if (meters < 1500) return "In one kilometer, ";
    return "In " + (Math.round(meters / 100) / 10).toFixed(1) + " kilometers, ";
  }
}

/**
 * Strip Valhalla's mid-string baked distance from a verbal_pre_transition or
 * verbal_transition_alert string. Valhalla emits the multi-cue chain in the
 * shape "<Verb phrase>. Then, in <dist> <unit>, <Imperative>" — the trailing
 * "Then, in N feet, X" is removed entirely, since the engine will prepend its
 * own live distance via formatDistancePrefix on the resulting head clause.
 *
 * Two regexes applied in sequence:
 *   1. Strip ". Then, in <dist>, <rest>" (mid-string distance chain) entirely
 *   2. Strip ". Then <rest>" (chain without distance) — pre-existing pattern,
 *      generalized to accept "Then," (comma form) per the latent bug found in
 *      adversarial review (the existing /\.\s*Then\s+/ regex requires whitespace
 *      after Then, fails on the comma form Valhalla actually emits).
 *
 * Returns text unchanged if neither pattern matched.
 */
function stripBakedDistance(text) {
  if (!text) return text;
  // Pattern 1: mid-string ". Then, in <dist>, <Imperative>." entirely
  // Anchored to end-of-string (text always ends with the chain in Valhalla).
  // (?:[^.]|\.(?=\d))* in the residual to avoid stopping at decimal point ("1.5 miles").
  text = text.replace(
    /\.\s*Then[\s,]+in\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km)\s*,\s*(?:[^.]|\.(?=\d))*\.?\s*$/,
    '.'
  );
  // Pattern 2: mid-string ". Then <rest>" (no distance) — broadened "Then\s+" to "Then[\s,]+"
  text = text.replace(
    /\.\s*Then[\s,]+(?:[^.]|\.(?=\d))*\.?\s*$/,
    '.'
  );
  // Pattern 3: leading "Then " — preserved from existing engine.
  text = text.replace(/^Then\s+/, '');
  return text;
}
```

**Test vectors for `formatDistancePrefix`** (verified against the reference implementation):

| Input | Expected output | Band reached |
|---|---|---|
| `(0, true)` | `""` | cutoff |
| `(29, true)` | `""` | cutoff (29 m = 95.1 ft < 30 m cutoff in meters) |
| `(31, true)` | `"In 100 feet, "` | feet (101.7 ft → round 100) |
| `(91, true)` | `"In 300 feet, "` | feet (298.6 ft → round 300) |
| `(290, true)` | `"In 1000 feet, "` | feet (951.4 ft → round 1000) |
| `(305, true)` | `"In a quarter mile, "` | quarter (1001 ft = 0.190 mi, in [1000, 1980) ft) |
| `(500, true)` | `"In a quarter mile, "` | quarter (1640 ft = 0.311 mi, in [1000, 1980) ft) |
| `(700, true)` | `"In half a mile, "` | half (2297 ft, in [1980, 3300) ft) |
| `(1100, true)` | `"In three quarters of a mile, "` | three-quarter (3609 ft, in [3300, 4620) ft) |
| `(1500, true)` | `"In one mile, "` | one (4921 ft, in [4620, 7920) ft) |
| `(2500, true)` | `"In 2 miles, "` | multi (8202 ft = 1.553 mi, ≥ 7920 ft, Math.round(1.553) = 2) |
| `(8000, true)` | `"In 5 miles, "` | multi (Math.round(4.972) = 5) |
| `(0, false)` | `""` | cutoff |
| `(29, false)` | `""` | cutoff |
| `(31, false)` | `"In 30 meters, "` | meters-low (round 10) |
| `(85, false)` | `"In 90 meters, "` | meters-low (round 10) |
| `(101, false)` | `"In 100 meters, "` | meters-mid (round 50) |
| `(480, false)` | `"In 500 meters, "` | meters-mid (round 50) |
| `(998, false)` | `"In 1000 meters, "` | meters-mid (round 50, edge-case label) |
| `(1000, false)` | `"In one kilometer, "` | one-km |
| `(1499, false)` | `"In one kilometer, "` | one-km (boundary) |
| `(1500, false)` | `"In 1.5 kilometers, "` | km-multi (Math.round(15)/10 = 1.5) |
| `(2345, false)` | `"In 2.3 kilometers, "` | km-multi (Math.round(23.45)/10 = 2.3) |

**Test vectors for `stripBakedDistance`** (each verified against the regex spec above on a fresh Node REPL):

| Input | Expected output | Why |
|---|---|---|
| `"Turn left onto Main."` | `"Turn left onto Main."` | no chain to strip |
| `"Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue."` | `"Drive east on West Villa Rita Drive."` | mid-string distance chain stripped (real Valhalla shape) |
| `"Turn right onto 24th Drive. Then Turn left onto West Union Hills Drive."` | `"Turn right onto 24th Drive."` | mid-string non-distance chain stripped (Pattern 2) |
| `"Turn right. Then, Turn right."` | `"Turn right."` | comma-form Then (Pattern 2 broadened) |
| `"Then turn left onto Union Hills Drive."` | `"turn left onto Union Hills Drive."` | leading Then stripped (Pattern 3 — existing) |
| `"In 1.5 miles, Merge onto I-5. Then, in 0.3 miles, Take exit 42."` | `"In 1.5 miles, Merge onto I-5."` | decimal-distance chain stripped (decimal-aware `\.(?=\d)`) |
| `"Drive north. Then, in a quarter mile, Keep left to stay on North Central Avenue."` | `"Drive north."` | fractional-words chain stripped |
| `"In 400 feet, Turn left."` | `"In 400 feet, Turn left."` | NOT a chain (single clause); leading "In" not stripped — caller's prefix logic handles it |

Note: the regex deliberately does NOT strip a *leading* "In <dist>, <Imperative>" pattern. Live Valhalla doesn't emit that shape on `verbal_pre_transition_instruction` or `verbal_transition_alert_instruction` for non-depart maneuvers (verified across 5 routes — auto, truck, bicycle, pedestrian, fr-FR — in adversarial R2). If a future Valhalla version starts emitting it, add a Pattern 4: `^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|...)\s*,\s*(?=[A-Z])/` (no `/i` flag — guard intact). Until observed, avoid speculative stripping that could over-match.

### 5.2 `checkVoice` changes

Three output paths in `checkVoice` are amended. **Critical ordering:** for each tier, mark `announcedSet` BEFORE constructing prefixed text. An exception in `formatDistancePrefix` or `stripBakedDistance` then leaves the maneuver "marked but never spoken" instead of "mute forever, will refire on every tick" (R1 F1.2).

**Far-tier path** (currently at [navigation.js:462-481](../../../frontend/navigation.js#L462-L481)):

```js
// existing: var farText = m.verbal_transition_alert_instruction || m.instruction || "";
// existing: announcedSet[farKey] = true;  ← mark FIRST (existing position is fine)
// existing: if (!muted && farText && onVoiceCb) onVoiceCb(farText);
//
// NEW: between mark-announced and onVoiceCb, transform farText:
var farText = m.verbal_transition_alert_instruction || m.instruction || "";
announcedSet[farKey] = true;
// NEW: GPS-recovery guard — skip prefix on first tick after DR/stale clear (G10).
var skipPrefix = consumeGPSRecoveryFlag();
if (!skipPrefix) {
  farText = stripBakedDistance(farText);
  var farPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
  if (farPrefix && farText.length > 0) {
    farText = farPrefix + farText.charAt(0).toLowerCase() + farText.slice(1);
  }
}
if (!muted && farText && onVoiceCb) onVoiceCb(farText);
```

**Near-tier base text** (currently at [navigation.js:399-417](../../../frontend/navigation.js#L399-L417)):

```js
var text = m.verbal_pre_transition_instruction || m.instruction || "";
// NEW: stripBakedDistance handles BOTH the trailing ". Then, in <dist>, <rest>" chain
// AND the existing leading-"Then" pattern. Replaces the prior two-line strip block.
text = stripBakedDistance(text);
if (text.length > 0) {
  text = text.charAt(0).toUpperCase() + text.slice(1);
}
// existing: announcedSet[nearKey] = true; announcedSet[farKey] = true;  ← mark FIRST
//
// NEW: GPS-recovery guard, then prefix prepend.
var skipPrefix = consumeGPSRecoveryFlag();
if (!skipPrefix) {
  var nearPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
  if (nearPrefix && text.length > 0) {
    text = nearPrefix + text.charAt(0).toLowerCase() + text.slice(1);
  }
}
// chain-append (see below) runs AFTER prefix is added to base text
```

**Chain-append path** (currently at [navigation.js:431-440](../../../frontend/navigation.js#L431-L440)):

```js
if (afterIdx < route.maneuvers.length) {
  var distBetween = distanceToManeuver(
    { segmentIndex: m.begin_shape_index, t: 0 }, afterIdx
  );
  if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
    var afterText = stripBakedDistance(route.maneuvers[afterIdx].instruction || "");
    if (afterText) {
      // Mark announcedSet BEFORE prefix construction (G11 exception safety).
      announcedSet[afterIdx + "-far"] = true;
      // GPS-recovery guard: same skipPrefix consumed by base text above already.
      // Don't consume again — single tick = single guard. Use the same value.
      var chainJoin;
      if (!skipPrefix) {
        var afterPrefix = formatDistancePrefix(distBetween, _geographicaUseImperial());
        if (afterPrefix) {
          var lcPrefix = afterPrefix.charAt(0).toLowerCase() + afterPrefix.slice(1);
          var lcAfter  = afterText.charAt(0).toLowerCase()  + afterText.slice(1);
          chainJoin = ", then " + lcPrefix + lcAfter;
        } else {
          chainJoin = ", then " + afterText;
        }
      } else {
        chainJoin = ", then " + afterText;
      }
      text = text.replace(/\.\s*$/, '') + chainJoin;
    }
  }
}
```

Note: `skipPrefix` is consumed exactly once per tick (in the near-tier or far-tier branch — whichever fires first), and the chain-append re-uses the same boolean rather than re-consuming. This way a single GPS recovery suppresses prefix on both base text and chain in the same tick.

### 5.3 Helpers

```js
// Module-scope state for GPS-recovery guard
var prevTickWasStaleOrDR = false;

function consumeGPSRecoveryFlag() {
  var nowFresh = !drActive && (Date.now() - lastGPSTime <= GPS_STALE_TIMEOUT);
  if (prevTickWasStaleOrDR && nowFresh) {
    prevTickWasStaleOrDR = false;
    return true;  // suppress prefix this tick
  }
  prevTickWasStaleOrDR = drActive || (Date.now() - lastGPSTime > GPS_STALE_TIMEOUT);
  return false;
}

function _geographicaUseImperial() {
  return typeof window !== 'undefined' && window._geographicaUseImperial !== false;
}
```

The `prevTickWasStaleOrDR` is updated on **every** call to `consumeGPSRecoveryFlag` so it reflects the most recent observation. A normal-flow tick (always fresh) sees `prevTickWasStaleOrDR = false`, sets it to `false`, returns `false`. A post-DR-recovery tick sees `prevTickWasStaleOrDR = true`, sets it to `false`, returns `true` (suppress). Subsequent ticks see `false` → `false` (normal flow).

`consumeGPSRecoveryFlag()` is called at most once per `checkVoice` invocation. If checkVoice returns early (e.g., past-maneuver guard), the flag is NOT consumed and stays armed for the next tick — which is correct (the recovery guard should fire on the first tick that *actually announces*, not the first tick that *runs checkVoice*).

### 5.4 Expected prompts on Villa Rita → Costco (re-derived from live Valhalla)

Pulled from the live `/valhalla/route` response on the dev stack at the time of v2 writing. All distances and prefixes are computed from the actual maneuver geometry:

| segment / tier / fire distance | current text | spec-v3 text |
|---|---|---|
| Seg 0 near+chain · 75 m, M[2] @ 459 m | "Turn left onto North 21st Avenue, then turn left onto West Union Hills Drive" | **"Turn left onto North 21st Avenue, then in a quarter mile, turn left onto West Union Hills Drive"** (floor-fire: base prefix suppressed; chain prefix preserved) |
| Seg 1 near · 75 m | "Turn left onto West Union Hills Drive" (m[2] far I11-suppressed by Seg 0 chain) | **"Turn left onto West Union Hills Drive"** (floor-fire: bare maneuver text) |
| Seg 2 far · 486 m @ 36 mph | "Turn right onto North Black Canyon Highway" | **"In a quarter mile, turn right onto North Black Canyon Highway"** (far-tier TTM-fire: prefix unchanged) |
| Seg 2 near · 75 m | "Turn right onto North Black Canyon Highway" | **"Turn right onto North Black Canyon Highway"** (floor-fire: bare maneuver text) |
| Seg 3 far · 477 m @ 36 mph | "Turn left onto West Utopia Road" | **"In a quarter mile, turn left onto West Utopia Road"** (far-tier TTM-fire: prefix unchanged) |
| Seg 3 near+chain · 75 m, M[5] @ 117 m | "Turn left onto West Utopia Road, then turn left onto North Black Canyon Highway" | **"Turn left onto West Utopia Road, then in 400 feet, turn left onto North Black Canyon Highway"** (floor-fire: base prefix suppressed; chain prefix preserved; 117 m = 384 ft → round 400) |
| Seg 4 near+chain · 75 m, M[6] @ 404 m (m[5] far I11-suppressed) | "Turn left onto North Black Canyon Highway, then turn right onto West Wescott Drive" | **"Turn left onto North Black Canyon Highway, then in a quarter mile, turn right onto West Wescott Drive"** (floor-fire: base suppressed; chain 404 m = 1325 ft = quarter-mile band) |
| Seg 5 near+chain · 75 m, M[7] @ 145 m (m[6] far I11-suppressed) | "Turn right onto West Wescott Drive, then turn right" | **"Turn right onto West Wescott Drive, then in 500 feet, turn right"** (floor-fire: base suppressed; chain 145 m = 476 ft → round 500) |
| Seg 6 near+chain · 75 m fire (75 < 145 m seg length, near-tier fires when dist crosses 75 m), M[8] @ 35 m (m[7] far I11-suppressed) | "Turn right, then turn right" | **"Turn right, then in 100 feet, turn right"** (floor-fire: base suppressed; chain 35 m = 115 ft → round 100, just above 30 m cutoff) |
| Seg 7 near+chain · entire seg (35 m seg length < 75 m floor, near-tier fires on first in-seg tick at ~35 m), M[9] arrival @ 227 m (m[8] far I11-suppressed) | "Turn right, then your destination is on the left" | **"Turn right, then in 700 feet, your destination is on the left"** (floor-fire: 35 m fire, base suppressed; chain 227 m = 745 ft → round 700) |

**Total prompts: 11.** Order unchanged. Text content amended per spec v3. Identical structural counts as TTM v3 ship.

**Speech-time check on the longest utterance** (Seg 3 chain at 25 mph):
- Text: "Turn left onto West Utopia Road, then in 400 feet, turn left onto North Black Canyon Highway."
- Word count: 15 words (vs. 18 in spec-v2 — base prefix dropped saves 3 words: "In 200 feet,").
- Fast voice (2.5 wps): 6.0 s + 0.5 s init = 6.5 s.
- Slow voice (1.8 wps): 8.3 s + 0.5 s = 8.8 s.
- Driver reaches Utopia at 75/9.2 = 8.2 s after fire (segment speed 9.2 m/s).
- **Outcome:** Fast voice completes the WHOLE compound at 6.5 s, well before the 8.2 s turn arrival — both clauses heard before the turn. Slow voice completes at 8.8 s, finishing the chain clause ~0.6 s after turn arrival (acceptable — chain is pre-announcing the next turn). The 1.5 s improvement over spec-v2 (saved by dropping "In 200 feet, " from base) tightens the actionable window without sacrificing the chain heads-up.

### 5.5 Tests

Add to `frontend/tests/engine/navigation.test.mjs`:

**Unit tests for `formatDistancePrefix`** (use the table in §5.1).

**Unit tests for `stripBakedDistance`** (use the table in §5.1).

**Integration tests** (using the existing test_runner.mjs fixtures):

- `TTM I13: imperial near-tier fires "In N feet, " prefix at 75 m floor` — run `fixtureVillaRitaCluster` at 11 m/s (note: fixture uses 30 m maneuver spacing = 98 ft, BELOW the 100 ft cutoff). Assert near-tier text starts with NO prefix (cutoff suppresses) and matches "Turn left onto Mulberry, then turn right onto Oak" (chain-append also below cutoff for the 30 m M[2]-M[3] gap).
- `TTM I13b: above-cutoff near-tier fires prefix` — synthesize a route with 200 m maneuver spacing and 75 m floor, run at 11 m/s. Assert near-tier text starts with `"In 200 feet, "` (75 m floor → 75 m × 3.28 = 246 ft → round 200) and chain-append contains `", then in 700 feet, "` (200 m between maneuvers → 656 ft → round 700).
- `TTM I13c: far-tier above-cutoff fires prefix at TTM distance` — synthesize a route with a long segment (1500 m), drive at 16 m/s, expect far-tier at ~480 m (TTM = 30 s). Assert far-tier text starts with `"In a quarter mile, "` (480 m = 1575 ft → in [1000, 1980) band).
- `TTM I13d: imperial vs metric dispatch` — toggle `_geographicaUseImperial`, run same fixture, assert text switches "feet/meters" / "mile/kilometer".
- `TTM I13e: cutoff suppresses prefix on short final hop` — fixtureVillaRitaCluster with 30 m spacing, assert near-tier text has no prefix.
- `TTM I13f: prompt count invariant on Villa Rita fixture with prefixes enabled` — assert count is unchanged from TTM v3 baseline (G9 regression guard).
- `TTM I14: GPS-recovery guard suppresses prefix on first post-DR tick` — set `drActive = true`, run a tick (no voice), set `drActive = false`, run another tick that triggers a near-tier fire. Assert the near-tier text has NO prefix (recovery suppression). Run a third tick; near-tier doesn't fire (announced), far-tier doesn't fire (announced). Run a fourth tick that fires far-tier on the next maneuver — assert prefix is present.
- `TTM I14b: GPS-stale recovery suppresses prefix on first fresh tick` — same as I14 but using `lastGPSTime` instead of `drActive`.
- `TTM I15: announcedSet marked before prefix construction (exception safety)` — mock `formatDistancePrefix` to throw. Run a tick that should fire near-tier. Assert: (a) `announcedSet[nearKey] === true` (mark happened before throw), (b) no `onVoiceCb` was called (text construction failed), (c) next tick does NOT re-fire (mark prevents replay).

**Integration test for the full pipeline (Codex F5.5):**

```js
test('TTM I13g: full pipeline strips Then-chain + applies live prefix', async (t) => {
  // Maneuver with mid-string baked-distance chain (real Valhalla shape).
  var input = "Drive east on West Villa Rita Drive. Then, in 900 feet, Turn left onto North 21st Avenue.";
  // Engine processes via stripBakedDistance → uppercase → formatDistancePrefix
  // with distToNext = 75 m (≈ 246 ft → "In 200 feet, ").
  var result = simulateNearTier(input, 75 /* m */, true /* imperial */);
  assert.equal(result, "In 200 feet, drive east on West Villa Rita Drive.");
  // Note: the Then-clause is stripped entirely; live-prefix replaces baked.
});
```

### 5.6 Invariants

- **I13 (new)**: Every voice prompt fired by `checkVoice` carries a live-distance prefix when `distToNext ≥ 30 m`. Prefix uses the TTM-snapshot distance, never Valhalla's baked distance.
- **I14 (new)**: On the first `checkVoice` invocation after `drActive` clears OR `gpsStale` clears, the prefix is suppressed for that tick. Prevents jarringly-precise distance prompts computed from a single recovered GPS sample.
- **I15 (new)**: `announcedSet` mutations happen BEFORE prefix construction. Exception in `formatDistancePrefix` or `stripBakedDistance` leaves the maneuver "marked but mute" (graceful degrade), never "fires repeatedly on every tick" (mute forever) or "fires twice."
- **I16 (new)**: `formatDistancePrefix` is monotone non-decreasing on the `meters` argument across band boundaries. The spoken value strictly never goes down as live distance increases. (Verified by the test table in §5.1; a property test asserting monotonicity over `[0, 10000]` in 10 m steps is recommended.)
- **G9 (preserved)**: prompt count, ordering, chain eligibility unchanged by Issue 2.

## 6. Ship gate (field-test acceptance)

Cameron re-drives the canonical Villa Rita → Costco route. Accept merge if:

1. **Issue 1 acceptance**: near-tier prompts fire noticeably earlier at surface speeds (~+1 s of post-speech buffer at 25 mph). "Broaches the intersection" symptom not observed.
2. **Issue 2 acceptance**: every appropriate prompt carries a distance prefix. Specifically:
   - Far-tier on Union Hills (~36 mph segment) speaks "In a quarter mile, turn right onto North Black Canyon Highway" instead of bare "Turn right onto North Black Canyon Highway."
   - Near-tier on surface streets (≥75 m fire distance) speaks "In 200 feet, turn left onto X" — provides the disambiguation Cameron flagged.
   - Chain-append carries its own distance: "..., then in 400 feet, turn left onto Y" not "..., then turn left onto Y."
   - Parking-lot turns at <30 m fire bare "Turn right" (cutoff suppression — preserves imminent-turn semantics).
3. **Regression**: total prompt count on the drive is 11 (TTM v3 baseline). No new class of unexpected announcements.
4. **GPS-recovery sanity**: if the drive includes a tunnel / overpass / multipath GPS dropout, the first post-recovery prompt (if any) speaks the maneuver text alone (no prefix). Easy to verify via the `_geographicaTTMDebugLog` instrumentation existing from TTM v3.

Unit/integration tests on `dev` before any field test:

- `node --test --test-force-exit frontend/tests/engine/` — all TTM + new I12/I13/I14/I15/I16 tests pass.
- Broader `python -m pytest tests/` — no regressions beyond the known `test_wake_lock_static.py` pre-existing failure.

## 7. Rollback

Both issues independently revertible. No persistent storage / backend / release-please impact. Issues 1 + 2 ship in the same PR but as separate commits so a partial revert is possible (revert Issue 2's ~200-line addition; keep Issue 1's 3-line floor change).

## 8. Open questions for plan-review

The plan-writing review should pin:

- **Slow-voice highway regression at ≥35 mph** (per §4.2 table): pre-existing TTM v3 behavior, but the prefix amplifies it. If field-tested as a problem, deferred fix is to lift TTM near tier from 3 s to 5 s in a future spec — out of scope here.
- **Chain-append speech overrun at slow voice** (Seg 3, §5.4): chain trailing-clause spoken during/after the FIRST turn at slow voice. Acceptable per analysis (informational not action-required), but flag for field observation.
- **Codex F5.3 (same-maneuver far/near distance ambiguity)**: deferred to NG9. If beta testers report this as confusing, a future spec adds an "imminent" form when the same maneuver's far-tier already fired.
- **`fixtureVillaRitaCluster` spacing (30 m) is below the new 100 ft cutoff**, so the existing fixture-based prompt-count test exercises a NO-PREFIX scenario, not the prefix logic itself. Add a new fixture `fixtureWiderCluster` with 200 m spacing for prefix-firing assertions (per §5.5 I13b).
