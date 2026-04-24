# Nav voice TTM follow-up — low-speed floor lift + live-distance prefix + sidebar BFCache restore

**Date:** 2026-04-24
**Agent:** pinyon
**Scope:** Three surgical fixes for field-surfaced issues on the live dev stack post-TTM-ship. All three are follow-ups to shipped work (TTM v3 `9a3836d`, voice-picker `97922b8`, sidebar persistence `f1687df`). Delivered together because they compose cleanly, share a field-test gate (Villa Rita → Costco), and all three are observable on the same drive.
**Files:** [frontend/navigation.js](../../../frontend/navigation.js) (Issues 1 + 2), [frontend/app.js](../../../frontend/app.js) (Issue 3), [frontend/tests/engine/navigation.test.mjs](../../../frontend/tests/engine/navigation.test.mjs) (Issue 1 + 2 tests), [tests/test_frontend_voice_picker.py](../../../tests/test_frontend_voice_picker.py) (Issue 3 structural test).
**Prior art:**
- [2026-04-20-nav-voice-ttm-design.md](2026-04-20-nav-voice-ttm-design.md) — TTM v3 spec (the baseline this amends for Issues 1 + 2)
- [2026-04-21-nav-voice-picker-design.md](2026-04-21-nav-voice-picker-design.md) — voice picker (orthogonal, but the `onVoiceCb` boundary we're preserving)
- Sidebar persistence commit `f1687df` (the partial fix Issue 3 completes)

## Revision history

- **v1 (2026-04-24)** — Initial design, brainstormed with agent pinyon and Cameron. Decisions locked:
  - Issue 1 scope: auto + bicycle (pedestrian unchanged).
  - Issue 1 direction: raise `VOICE_DISTANCE_FLOOR` only, leave `VOICE_TTM` tier thresholds unchanged.
  - Issue 1 values: auto 50 → 65 m, bicycle 30 → 40 m (+1.3 s post-speech buffer at the 25 mph field symptom, absorbs variable TTS init latency).
  - Issue 2 scope: prefix far-tier + near-tier + chain-append; apply to all three costings.
  - Issue 2 format: fractional miles à la Google Maps (feet under 1000 ft, then 1/4 · 1/3 · 1/2 · 3/4 · 1 mile bands, then whole miles).
  - Issue 2 cutoff: omit prefix below 100 ft / 30 m.
  - Issue 3 mechanism: add `pageshow` listener that calls `restoreLastSidebarTab()` when `e.persisted === true`.
  - Pending: 5-round adversarial review (at least one round via Codex).

## 1. Summary

Three field-surfaced defects from Cameron's post-TTM-ship field testing:

1. **Near-tier fires too close at surface speeds <25 mph.** The 50 m distance floor at [navigation.js:53](../../../frontend/navigation.js#L53) governs whenever `3 × speed < 50`, which is all speeds below ~37 mph. At 25 mph the prompt fires 4.5 s before the intersection; after ~3 s of TTS speech plus ~0.5 s network/init latency, the driver has effectively 0 s of post-speech buffer and the prompt completes "as the vehicle broaches the intersection on a 3-way junction." Fix: raise the floor (auto 50→65, bicycle 30→40) to buy +1.3 s of post-speech buffer at the symptom speed while leaving TTM-governed speeds (≥ 37 mph) unchanged.

2. **Prompts lack distance context.** Valhalla's `verbal_transition_alert_instruction` for most turns on the canonical Villa Rita → Costco route is the bare turn ("Turn left onto West Utopia Road.") — no distance. Driven at 36 mph on Union Hills, the far-tier fires at 486 m (≈ 0.3 mi) but the TTS says nothing about distance. The near-tier's chain-append (", then turn left onto Utopia Road") also carries no distance ever. A driver with eyes-on-road can't disambiguate "turn right" meaning imminent vs. a third of a mile out. Fix: compute the live distance from the TTM snapshot already in hand inside `checkVoice` (`distToNext` and a new `distBetween` for chain-append), format by `useImperial` preference, and prepend.

3. **Sidebar tab resets to "Layers" after reopening during active navigation.** The `f1687df` fix stores the last-selected tab in localStorage and restores it in the `DOMContentLoaded` handler, but iOS Safari restores backgrounded pages via the BFCache — which fires `pageshow` with `e.persisted === true` and **does not fire `DOMContentLoaded`**. So the restore logic never runs on the real-world trigger. Hardcoded `class="tab-btn active"` on the Layers button in [index.html:46](../../../frontend/index.html#L46) wins the BFCache restore. Fix: add a `pageshow` listener that invokes `restoreLastSidebarTab()` when `e.persisted` is true. The existing restore function is idempotent (early-returns if the target tab already has `.active`), so the call is safe on every pageshow.

## 2. Goals & non-goals

### Goals

- **G1 (Issue 1).** At the field-symptom speed (25 mph surface streets), the near-tier fires ≥ 1 s earlier than current, giving ≥ 2.8 s of post-speech buffer (up from ~1.5 s baseline). Absolute change: fire at 65 m instead of 50 m on auto, 40 m instead of 30 m on bicycle.
- **G2 (Issue 1).** High-speed (≥ 37 mph) near-tier timing is bit-identical to pre-fix — the floor is inactive whenever `3 × speed ≥ floor`.
- **G3 (Issue 1).** Stationary-driver invariants from TTM spec v3 (I3, I4) remain structurally correct with the new floor values. I3: zero announcements when stationary beyond the new floor. I4: near-tier fires when stationary within the new floor.
- **G4 (Issue 2).** Every voice prompt fired by `checkVoice` carries a live-distance prefix unless the distance is below the small-distance cutoff (30 m / 100 ft).
- **G5 (Issue 2).** The chain-appended suffix (", then <next maneuver>") carries its own distance prefix measured from the current maneuver to the next-after-next.
- **G6 (Issue 2).** Format follows user unit preference. Imperial: sub-1000 ft in feet rounded to 100; ≥ 1000 ft in fractional miles through 1 mile; ≥ 1.25 mi in whole miles. Metric: sub-900 m in meters rounded to 50 (to 10 under 100 m); ≥ 900 m in kilometers rounded to 0.1.
- **G7 (Issue 2).** No change in prompt count, prompt ordering, or chain-eligibility logic. Issue-2 is a pure presentation-layer change; counts must remain invariant on the canonical Villa Rita → Costco trace (verified as 11 under v3 in this design doc).
- **G8 (Issue 2).** When Valhalla bakes a distance into the source text (rare in alert-tier, occasionally present in the near-tier's multi-cue depart), we strip it before prepending the live distance, to avoid double-stating ("In 200 feet, In 900 feet, Turn left onto 21st Avenue").
- **G9 (Issue 3).** Reopening the sidebar after any iOS Safari BFCache restore-event produces the tab that was active before the backgrounding, matching the user expectation Cameron field-tested.
- **G10 (Issue 3).** Normal (non-BFCache) page loads continue to work identically. The `pageshow` listener is additive, and `restoreLastSidebarTab()` is idempotent.
- **G11 (across issues).** Villa Rita → Costco field drive (the TTM v3 ship gate) still produces the same 11 prompts with the same ordering. Timing shifts (Issue 1), text content changes (Issue 2), and sidebar-state survival (Issue 3) are the only observable deltas.

### Non-goals

- **NG1.** No change to `VOICE_TTM` tier thresholds (`[30, 3]` auto / `[20, 3]` bicycle / `[15, 2]` pedestrian). The 30-second far-tier and 3-second near-tier advance-notice semantics are correct; only the floor was wrong.
- **NG2.** No change to pedestrian profile floor (stays 15 m). Walking-pace scenarios have ample buffer today; a change here would expand scope without field evidence.
- **NG3.** No change to `NEXT_AFTER_NEXT_DISTANCE = 500 m` chain-eligibility threshold. Chain math is unchanged.
- **NG4.** No introduction of TTS-aware announcement semantics (e.g., reading back the last N words of a long prompt, suppression based on measured speech duration). Those would require cross-file wiring into `nav-ui.js`'s speech pipeline. Out of scope.
- **NG5.** No changes to `frontend/nav-ui.js`. The `onVoiceCb(text)` boundary is preserved; text is formed inside `navigation.js` and handed to `nav-ui` unchanged in shape.
- **NG6.** No change to Valhalla routing. We consume the route output as-is; the distance-prefix feature uses live engine-side distances, not Valhalla's baked route-planning distances.
- **NG7.** No retroactive amendment of TTM v3 spec invariants I1–I11. I3 and I4's floor references now resolve to 65/40/15 instead of 50/30/15, but the invariant shapes are unchanged.
- **NG8.** No deprecation of `useImperial` preference or changes to how it's exposed. `window._geographicaUseImperial` continues to be the source of truth.
- **NG9.** No changes to sidebar tab click semantics, localStorage key name, or the `VALID_SIDEBAR_PANELS` whitelist.
- **NG10.** No attempt to detect or handle the "memory-kill without BFCache" path (full reload past the BFCache window). The existing `DOMContentLoaded` path handles that case; the bug was the missing BFCache path.

## 3. Architecture

```
                                                        
  Issue 1: frontend/navigation.js                       
  ────────────────────────────────                      
  VOICE_DISTANCE_FLOOR.auto    50 → 65                  
  VOICE_DISTANCE_FLOOR.bicycle 30 → 40                  
  VOICE_DISTANCE_FLOOR.pedestrian 15 (unchanged)        
                                                        
  Issue 2: frontend/navigation.js                       
  ────────────────────────────────                      
  new: formatDistancePrefix(meters, useImperial)        
  new: stripBakedDistance(text)                         
  amended: checkVoice() prepends on all 3 output paths  
           (far, near, chain-append)                    
                                                        
  Issue 3: frontend/app.js                              
  ──────────────────────                                
  new: window.addEventListener('pageshow', ...)         
       in DOMContentLoaded block, guarded by            
       e.persisted                                      
                                                        
```

No cross-file wiring. Each issue is localized.

## 4. Issue 1 — near-tier floor lift

### 4.1 Constants

Current constants in [navigation.js:52-56](../../../frontend/navigation.js#L52-L56):

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
  auto:       65,  // +15 m, ≈ +1.3 s post-speech buffer at 25 mph surface-street symptom
  bicycle:    40,  // +10 m, mirror of auto delta
  pedestrian: 15   // unchanged (ample buffer at walking pace)
};
```

### 4.2 Buffer table (auto profile, for reviewers)

Fire distance = `max(3 × speed, floor)`. Post-speech buffer = fire_distance / speed − 3 s TTS (~3 s typical utterance, ~0.5 s init latency folded in via the speech window).

| speed | current (50 m floor) | new (65 m floor) | delta |
|---|---|---|---|
| 15 mph / 6.7 m/s | 50 m / 7.5 s / 4.5 s buffer | 65 m / 9.7 s / 6.7 s buffer | +2.2 s |
| 20 mph / 8.9 m/s | 50 m / 5.6 s / 2.6 s buffer | 65 m / 7.3 s / 4.3 s buffer | +1.7 s |
| **25 mph / 11.2 m/s** (symptom) | **50 m / 4.5 s / 1.5 s buffer** | **65 m / 5.8 s / 2.8 s buffer** | **+1.3 s** |
| 30 mph / 13.4 m/s | 50 m / 3.7 s / 0.7 s | 65 m / 4.9 s / 1.9 s | +1.2 s |
| 37 mph / 16.7 m/s (floor boundary, new) | 50 m / 3.0 s / 0 s | 65 m / 3.9 s / 0.9 s | +0.9 s |
| 45 mph / 20.1 m/s (TTM regime) | 60 m / 3.0 s / 0 s | 65 m / 3.2 s / 0.2 s | +0.2 s |
| ≥ 48 mph (TTM fully governs) | `3 × speed` | `3 × speed` (no change) | 0 |

### 4.3 Invariant amendments to TTM v3 spec

- **I3** (unchanged shape, new value): "zero announcements when the driver is stationary beyond the distance floor" — floor for auto is now 65 m, bicycle 40 m, pedestrian 15 m.
- **I4** (unchanged shape, new value): "near-tier fires when the driver is stationary ≤ floor from the maneuver" — same value update.
- New **I12**: "raising the floor from 50 → 65 m preserves exactly-2-prompts-per-maneuver (G1 in TTM v3) when the driver enters from outside the far-tier threshold." Far-tier is TTM-governed and independent of the floor; near-tier still fires exactly once per maneuver regardless of floor. Formal check: on any route with maneuver spacing > 65 m, near-tier fires at distance = 65 m for low-speed approach; spacing > 195 m guarantees no interference between consecutive maneuvers' near-tiers.

### 4.4 Tests (engine)

New tests in `frontend/tests/engine/navigation.test.mjs`:

- `TTM I12: floor 65 auto fires near-tier at 65 m at 11.2 m/s` — parameterize existing floor-governs-below-TTM test over the new value.
- `TTM I12: floor 40 bicycle fires near-tier at 40 m at 5 m/s` — bicycle mirror.
- `TTM I12: floor change does not affect prompt count on Villa Rita synthetic fixture` — run `fixtureVillaRitaCluster`, assert count is still 3 prompts. Keeps G11 (invariant count) honest.
- `TTM I12: floor change does not affect mixed-spacing cluster prompt count` — run `fixtureMixedSpacingCluster`, assert count is still 4 prompts (per TTM v3 I11 chain extension).

Existing tests at `TTM G1: fires exactly 2 prompts per maneuver at highway speed` must continue to pass with no modification (high-speed is floor-independent).

## 5. Issue 2 — live-distance prefix

### 5.1 New helpers

Both helpers live in `navigation.js` as private functions (module-scope), exported via `_geographicaNavEngineInternals` for test access.

```js
// Small-distance cutoff — below this, prompts read as imminent ("turn right").
var DISTANCE_PREFIX_CUTOFF_METERS = 30; // ≈ 100 ft

/**
 * Format a live distance in meters as a human-readable prefix, matching
 * Google Maps conventions. Empty string means "below the cutoff, no prefix".
 * Imperial (useImperial=true):
 *   <100 ft: ""
 *   [100, 1000) ft: "In N00 feet, " (rounded to nearest 100)
 *   [1000, 5/16 mi) ft: "In 1/4 mile, "     (1000–1650 ft)
 *   [5/16, 7/16) mi:  "In 1/3 mile, "       (1650–2310 ft)
 *   [7/16, 5/8) mi:   "In 1/2 mile, "       (2310–3300 ft)
 *   [5/8, 7/8) mi:    "In 3/4 mile, "       (3300–4620 ft)
 *   [7/8, 3/2) mi:    "In 1 mile, "         (4620–7920 ft)
 *   >= 3/2 mi:        "In N miles, " (rounded to nearest whole mile; smallest
 *                                    possible N is 2 since 3/2 rounds to 2)
 * Metric (useImperial=false):
 *   <30 m: ""
 *   [30, 100) m: "In N0 meters, " (rounded to nearest 10)
 *   [100, 900) m: "In NN0 meters, " (rounded to nearest 50)
 *   >= 900 m: "In N.N kilometers, " (rounded to 1 decimal)
 */
function formatDistancePrefix(meters, useImperial) { ... }

/**
 * Strip a leading distance-prefix from Valhalla-supplied text, if any.
 * Handles both numeric ("In 400 feet, ") and fractional ("In a quarter mile, ")
 * forms. Conservative: only strips when followed by a capital letter starting
 * the real instruction. Returns text unchanged if no prefix matched.
 */
function stripBakedDistance(text) { ... }
```

Exact regex for `stripBakedDistance`:

```js
// Matches "In <quantity> <unit>, " where <quantity> is any reasonable combo
// of digits, decimal points, fraction words ("quarter", "half", "third"), and
// articles ("a", "an"), and <unit> is a distance unit. The non-greedy middle
// capture plus the mandatory `\s<unit>\s*,` terminator prevents over-matching
// into the real instruction. The `(?=[A-Z])` lookahead ensures we only strip
// when the residual starts with a capital — an additional guard that the
// stripped span was in fact a prefix, not the start of the instruction.
var BAKED_DISTANCE_RE = /^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km|m)\s*,\s*(?=[A-Z])/i;
```

Test vectors (all should match):
- `"In 400 feet, Turn left."` → matches `"In 400 feet, "`, residual `"Turn left."`
- `"In a quarter mile, Turn left."` → matches, residual `"Turn left."`
- `"In half a mile, Turn."` → matches
- `"In a half mile, Turn."` → matches
- `"In 1.5 miles, Merge onto I-5."` → matches
- `"In 500 meters, Turn."` → matches

Non-match (regex returns unchanged):
- `"Turn left onto Main."` (no leading "In")
- `"In 400 feet, turn left."` (lowercase `t` after comma — deliberate guard; won't strip)
- `"In 400 feet, you will turn."` (lowercase `y`)
- `"Interesting observation. Turn left."` (no distance unit)

### 5.2 `checkVoice` changes

Three output paths inside `checkVoice` are amended:

**Far-tier path** (currently at [navigation.js:462-481](../../../frontend/navigation.js#L462-L481)):

```js
// NEW: strip any baked-in distance from Valhalla, then prepend live distance.
var farText = stripBakedDistance(
  m.verbal_transition_alert_instruction || m.instruction || ""
);
var farPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
if (farPrefix && farText.length > 0) {
  // Prefix ends with ", " so lowercase the first letter of farText for flow.
  farText = farPrefix + farText.charAt(0).toLowerCase() + farText.slice(1);
}
```

**Near-tier base text** (currently at [navigation.js:399-417](../../../frontend/navigation.js#L399-L417), prior to the existing Valhalla "Then" strip).

Edit the existing block so that `stripBakedDistance` runs BEFORE the uppercase normalization (the strip's `(?=[A-Z])` guard requires the remaining text to start with a capital already, so order is load-bearing), and the live-distance prefix prepend happens AFTER uppercase is applied. That preserves existing capitalization semantics when no prefix is used.

```js
var text = m.verbal_pre_transition_instruction || m.instruction || "";
// Existing "Then" strips are preserved (load-bearing — they remove Valhalla's
// baked chain so I11 suppression is semantically correct).
text = text.replace(/\.\s*Then\s+[^.]*\.?\s*$/i, '.');
text = text.replace(/^Then\s+/i, '');
// NEW: strip baked distance BEFORE uppercase (strip guard checks [A-Z] on residual).
text = stripBakedDistance(text);
if (text.length > 0) {
  text = text.charAt(0).toUpperCase() + text.slice(1);
}
// NEW: prepend live-distance prefix when above cutoff.
var nearPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial());
if (nearPrefix && text.length > 0) {
  text = nearPrefix + text.charAt(0).toLowerCase() + text.slice(1);
}
```

**Near-tier chain-append** (currently at [navigation.js:431-440](../../../frontend/navigation.js#L431-L440)):

```js
if (distBetween <= NEXT_AFTER_NEXT_DISTANCE) {
  var afterText = stripBakedDistance(route.maneuvers[afterIdx].instruction || "");
  if (afterText) {
    // NEW: prepend live distance to the chain-append. Lowercase BOTH the
    // prefix's "In" and the instruction's first letter so the sentence reads
    // naturally: "Turn left onto 21st, then in 1/4 mile, turn left onto Union".
    // When no prefix applies, preserve the existing capital-first behavior
    // ("Turn left onto 21st, then Turn left onto Union") — capitalized second
    // clause matches the current ship.
    var afterPrefix = formatDistancePrefix(distBetween, _geographicaUseImperial());
    var chainJoin;
    if (afterPrefix) {
      var lcPrefix = afterPrefix.charAt(0).toLowerCase() + afterPrefix.slice(1);
      var lcAfter  = afterText.charAt(0).toLowerCase()  + afterText.slice(1);
      chainJoin = ", then " + lcPrefix + lcAfter;
    } else {
      chainJoin = ", then " + afterText;
    }
    text = text.replace(/\.\s*$/, '') + chainJoin;
    announcedSet[afterIdx + "-far"] = true;
  }
}
```

### 5.3 `_geographicaUseImperial()` helper

The engine reads the global at call time (never cached), matching the existing pattern in `distMeters` computation at [nav-ui.js:290](../../../frontend/nav-ui.js#L290):

```js
function _geographicaUseImperial() {
  return typeof window !== 'undefined' && window._geographicaUseImperial !== false;
}
```

Default true (imperial) when the global is undefined, matching `app.js:123` default.

### 5.4 Expected prompts on Villa Rita → Costco

Comparing current vs spec-compliant output:

| segment / tier / fire distance | current | spec-compliant |
|---|---|---|
| Seg 0 near+chain · fire @ 65 m, M2 @ 459 m | Turn left onto North 21st Avenue, then turn left onto West Union Hills Drive | **In 200 feet**, turn left onto North 21st Avenue, **then in 1/4 mile**, turn left onto West Union Hills Drive |
| Seg 2 far · fire @ 486 m @ 36 mph | Turn right onto North Black Canyon Highway | **In 1/4 mile**, turn right onto North Black Canyon Highway |
| Seg 3 far · fire @ 477 m @ 36 mph | Turn left onto West Utopia Road | **In 1/4 mile**, turn left onto West Utopia Road |
| Seg 4 near+chain · fire @ 65 m, M6 @ 117 m | Turn left onto North Black Canyon Highway, then turn left onto West Wescott Drive | **In 200 feet**, turn left onto North Black Canyon Highway, **then in 400 feet**, turn left onto West Wescott Drive |
| Seg 7 near+chain · fire @ 35 m (seg length), M8 @ 35 m | Turn right, then turn right | **In 100 feet**, turn right, **then in 100 feet**, turn right |

Observations: (a) prompt count unchanged (11); (b) prompt ordering unchanged; (c) distances on chain-append are the between-maneuver distances (not accumulated from the driver), matching the engine's existing `distBetween` variable.

### 5.5 Tests (engine)

New tests in `navigation.test.mjs`:

- **Unit tests for `formatDistancePrefix`** (imperial). All computed: feet = meters × 3.28084; miles = feet / 5280. Boundary comments give the matching band.
  - `formatDistancePrefix(0, true) === ""` (below cutoff)
  - `formatDistancePrefix(29, true) === ""` (95.1 ft, below 100 ft cutoff)
  - `formatDistancePrefix(31, true) === "In 100 feet, "` (101.7 ft, rounds to 100)
  - `formatDistancePrefix(91, true) === "In 300 feet, "` (298.6 ft)
  - `formatDistancePrefix(290, true) === "In 1000 feet, "` (951.4 ft, still in feet band since &lt; 1000 ft, rounds to 1000). **Note**: the feet-band max of 999.9 ft never rounds to 1000 because anything &ge; 950 ft but &lt; 1000 ft rounds to 1000 — so feet-band's output can legitimately say "1000 feet". This is correct Google-Maps-like behavior.
  - `formatDistancePrefix(305, true) === "In 1/4 mile, "` (1000.66 ft = 0.1895 mi, just into the [0.19, 5/16) band)
  - `formatDistancePrefix(500, true) === "In 1/4 mile, "` (1640.4 ft = 0.3107 mi, still in [0.19, 5/16=0.3125) band)
  - `formatDistancePrefix(504, true) === "In 1/3 mile, "` (1653.6 ft = 0.3132 mi, crosses into [5/16, 7/16) band)
  - `formatDistancePrefix(700, true) === "In 1/3 mile, "` (2296.6 ft = 0.4349 mi, in [5/16, 7/16=0.4375) band)
  - `formatDistancePrefix(800, true) === "In 1/2 mile, "` (2624.7 ft = 0.4971 mi, in [7/16, 5/8) band)
  - `formatDistancePrefix(1100, true) === "In 3/4 mile, "` (3608.9 ft = 0.6835 mi, in [5/8, 7/8) band)
  - `formatDistancePrefix(1500, true) === "In 1 mile, "` (4921.3 ft = 0.9321 mi, in [7/8, 5/4) band)
  - `formatDistancePrefix(2100, true) === "In 1 mile, "` (6889.8 ft = 1.305 mi, just crosses 5/4 — rounds to 1, so 1 mile. Edge-case check: is "round to nearest whole" = `Math.round(miles)`? 1.305 rounds to 1. ✓)
  - `formatDistancePrefix(3200, true) === "In 2 miles, "` (10498.7 ft = 1.988 mi, rounds to 2)
  - `formatDistancePrefix(8000, true) === "In 5 miles, "` (26247 ft = 4.972 mi, rounds to 5)
- **Unit tests for `formatDistancePrefix`** (metric, useImperial=false):
  - `formatDistancePrefix(29, false) === ""`
  - `formatDistancePrefix(31, false) === "In 30 meters, "`
  - `formatDistancePrefix(85, false) === "In 90 meters, "` (rounds to 10)
  - `formatDistancePrefix(480, false) === "In 500 meters, "` (rounds to 50)
  - `formatDistancePrefix(950, false) === "In 1.0 kilometers, "`
  - `formatDistancePrefix(2345, false) === "In 2.3 kilometers, "`
- **Unit tests for `stripBakedDistance`**:
  - `stripBakedDistance("Turn left onto Main.") === "Turn left onto Main."` (no-op)
  - `stripBakedDistance("In 400 feet, Turn left onto Main.") === "Turn left onto Main."`
  - `stripBakedDistance("In a quarter mile, Turn left.") === "Turn left."`
  - `stripBakedDistance("In 1.5 miles, Merge onto I-5.") === "Merge onto I-5."`
  - `stripBakedDistance("In 500 meters, Turn.") === "Turn."`
  - **Negative case**: `stripBakedDistance("In 400 feet, you will turn.") === "In 400 feet, you will turn."` (no capital-letter boundary; strip guard prevents eating real instruction)
- **Integration tests**:
  - `TTM I13: near-tier fires "In 200 feet, " prefix at 65 m floor` — run existing fixtureVillaRitaCluster at 11 m/s, assert first voice text starts with "In 200 feet, " (imperial default).
  - `TTM I13: far-tier fires "In 1/4 mile, " prefix at 486 m` — synthesize a route with a long segment, run at 16 m/s, assert far-tier text starts with "In 1/4 mile, ".
  - `TTM I13: chain-append carries its own distance prefix` — run fixtureVillaRitaCluster (30 m spacing), assert near-tier text contains ", then in 100 feet, " (30 m * 3.28 = 98 ft → rounds to 100).
  - `TTM I13: imperial vs metric dispatch` — toggle `_geographicaUseImperial`, run same fixture, assert text switches "feet"/"meters".
  - `TTM I13: cutoff suppresses prefix on short final hop` — use fixtureShortHop (<30 m seg), assert near-tier fires without a distance prefix.
  - `TTM I13: prompt count invariant on Villa Rita fixture with prefixes enabled` — run fixtureVillaRitaCluster, assert count is still 3. (G7 regression guard.)

### 5.6 Invariant additions

- **I13 (new)**: "Every voice prompt fired by `checkVoice` that represents a distance ≥ cutoff carries a live-distance prefix. Prefixes are computed from TTM-snapshot distances (`distToNext` for the current maneuver, `distBetween` for the chain-append), never from Valhalla's route-planning distances."
- **I14 (new)**: "Prompt count on any route is independent of whether prefixes are enabled. The prefix is a pure text transform; it neither adds nor removes firings."

## 6. Issue 3 — sidebar BFCache restore

### 6.1 Root cause recap

iOS Safari restores backgrounded pages from the back/forward cache (BFCache). BFCache restores fire `pageshow` with `event.persisted === true` and **do not fire `DOMContentLoaded`**. The `f1687df` restore is wired only to `DOMContentLoaded`, so on a BFCache restore the hardcoded `class="tab-btn active"` on the Layers button ([index.html:46](../../../frontend/index.html#L46)) + `class="panel active"` on `#layers-panel` ([index.html:53](../../../frontend/index.html#L53)) remain visually active, while localStorage still contains the user's last-chosen tab.

### 6.2 Change

Add a single `pageshow` listener in the DOMContentLoaded block in [app.js:4120-4132](../../../frontend/app.js#L4120-L4132):

```js
document.addEventListener('DOMContentLoaded', function () {
  initMap();
  initSidebarTabs();
  initLayerControls();
  initSearch();
  initRouting();
  initImport();
  initGPS();
  initAdmin();
  restoreLastSidebarTab();
  if (window.VoicePicker && typeof window.VoicePicker.init === 'function') {
    window.VoicePicker.init();
  }
  // ... (rest unchanged)
});

// NEW: iOS Safari restores backgrounded pages from BFCache without firing
// DOMContentLoaded. Re-run tab restoration so persisted selection survives
// iOS memory-kill / app-switch cycles during active navigation.
// restoreLastSidebarTab() is idempotent — early-returns when the target
// tab is already active, so non-BFCache pageshow events are no-ops.
window.addEventListener('pageshow', function (e) {
  if (e.persisted) restoreLastSidebarTab();
});
```

The listener is placed at module scope, outside DOMContentLoaded, so it wires up immediately during script parsing — not dependent on DOMContentLoaded having fired.

### 6.3 Tests (structural)

Extend `tests/test_frontend_voice_picker.py` (the nearest-adjacent structural-test home) with:

```python
def test_sidebar_tab_restore_covers_bfcache():
    """f1687df closed the DOMContentLoaded path; this test closes the BFCache
    path. iOS Safari restores backgrounded pages via BFCache, which fires
    pageshow(e.persisted=true) but NOT DOMContentLoaded.
    """
    src = (REPO_ROOT / "frontend/app.js").read_text()
    # Original DOMContentLoaded restoration path must still exist
    assert "DOMContentLoaded" in src
    assert "restoreLastSidebarTab()" in src
    # BFCache path — pageshow listener that calls restoreLastSidebarTab when e.persisted
    m = re.search(
        r"addEventListener\s*\(\s*['\"]pageshow['\"]\s*,\s*function\s*\([^)]*\)\s*\{[^}]{0,400}"
        r"e\.persisted[^}]{0,200}?restoreLastSidebarTab\s*\(",
        src,
    )
    assert m is not None, (
        "Expected a window.addEventListener('pageshow', fn) listener that invokes "
        "restoreLastSidebarTab() when e.persisted is true. Without this, iOS Safari "
        "BFCache restores drop the user back to the default Layers tab."
    )
```

No unit test is practical here — jsdom does not simulate BFCache. A structural regex test is the right rigor given the project's existing test posture (see [test_frontend_voice_picker.py::test_sidebar_tab_persistence_wired](../../../tests/test_frontend_voice_picker.py) as precedent).

### 6.4 Invariants

- **Sidebar persistence across full page reloads** (existing, preserved): `f1687df`'s DOMContentLoaded-triggered `restoreLastSidebarTab()` continues to fire on parse-from-network loads.
- **Sidebar persistence across BFCache restores** (new): `pageshow` with `e.persisted === true` also fires `restoreLastSidebarTab()`. Composes with the DOMContentLoaded path for a full cover over all page-lifecycle events that can drop the user back to the default tab.
- **Idempotency**: calling `restoreLastSidebarTab()` when the target tab is already active is a no-op (existing early-return at [app.js:4113](../../../frontend/app.js#L4113)). Non-BFCache `pageshow` events (e.g., normal first loads where DOMContentLoaded already restored, subsequent `pageshow` with `e.persisted === false`) therefore cost nothing.

## 7. Ship gate (field-test acceptance)

Cameron re-drives the Villa Rita → Costco route (canonical TTM v3 regression route). Accept the merge if:

1. **Issue 1 acceptance**: near-tier prompts fire noticeably earlier at surface-street speeds (≈ 1 second more advance notice than the current ship). "Broaches the intersection" symptom no longer observed.
2. **Issue 2 acceptance**: every prompt carries a distance prefix when appropriate. Specifically, far-tier "Turn right onto North Black Canyon Highway" is now heard as "In 1/4 mile, turn right onto North Black Canyon Highway." Chain-appends include their own distance. Parking-lot turns (<30 m) remain unprefixed ("turn right").
3. **Issue 3 acceptance**: initiate navigation, switch to Route tab, close sidebar, let phone sleep/app switch for ≥ 2 minutes, reopen Geographica, reopen sidebar → Route tab is still active. Also: hard-reload → sidebar opens to Route tab (existing behavior preserved).
4. **Regression**: total prompt count on the drive is 11 (same as TTM v3). No new class of unexpected announcements.

Unit/integration tests green on `dev` branch before any field test:

- `node --test --test-force-exit frontend/tests/engine/` — all TTM + new I12/I13/I14 tests pass
- `python -m pytest tests/test_frontend_voice_picker.py` — sidebar BFCache structural test passes
- Broader `python -m pytest tests/` — no regressions beyond the known `test_wake_lock_static.py::test_wake_lock_js_exists_and_exports_api` pre-existing failure

## 8. Rollback plan

Each issue is independently revertible:

- **Issue 1** rollback: revert the `VOICE_DISTANCE_FLOOR` constant change (single-commit, pure value change).
- **Issue 2** rollback: revert the `checkVoice` text-forming blocks and delete `formatDistancePrefix` + `stripBakedDistance`. Engine behavior returns to TTM v3 text shape.
- **Issue 3** rollback: delete the `pageshow` listener. BFCache restores go back to dropping users on Layers tab.

None of the three changes affect persistent storage schema, backend contracts, or release-please versioning triggers. All three are additive/scalar frontend changes; release type is `fix(nav)` for Issues 1 + 3 and `feat(nav)` for Issue 2 (new distance-prefix presentation is user-observable).

## 9. Open questions for adversarial review

The 5-round adversarial review should stress-test:

- **Issue 1**: does the new 65 m floor for auto interact badly with TTM v3 I11 chain-extension in mixed-spacing clusters (40–90 m spacing)? Spec §4 of TTM v3 claimed I11 already bounds prompt count there; verify with the new floor.
- **Issue 2 (G8)**: are there Valhalla output shapes not covered by the regex — e.g., "In about half a mile, ..." or "In three quarters of a mile, ..."? Partial strips could produce "In 200 feet, three quarters of a mile, Turn left..." nonsense.
- **Issue 2 (G6)**: does the fractional-miles band produce reasonable output when the live distance is right at a band boundary (e.g., 1649 ft: 1/4 mile vs 1650 ft: 1/3 mile)? One-foot rounding should not produce jarringly different announcements on adjacent ticks.
- **Issue 2 (G7)**: are there edge-case Valhalla texts where the baked-distance strip plus prefix-prepend produces ungrammatical output (e.g., "In 200 feet, t" if the instruction was just one letter post-strip)?
- **Issue 2 (G8)**: chain-append with empty `afterText` (Valhalla omits instruction on some maneuvers) — does the existing guard (`if (afterText)`) still suppress the chain appropriately under the new branch?
- **Issue 3**: the spec asserts BFCache is the primary cause. What other page-lifecycle events could cause the observed symptom? `pagehide` triggering a tab reset? Iframe lifecycle? Audio/media session interruption with partial re-render? Rule these in or out with a Codex cross-validation round.
- **Issue 3**: on Android Chrome, does BFCache ever engage for this PWA? If so, the same listener handles it; if not, this fix is iOS-specific. Either way the fix is correct; clarify the claim.
- **Cross-issue**: does adding the distance-prefix text make the near-tier utterance noticeably longer, eating into the +1.3 s post-speech buffer we just bought? Speech timing math: "In 1/4 mile, turn right onto Black Canyon Highway" vs "Turn right onto Black Canyon Highway" — the prefix adds ~0.7 s of speech. At the symptom speed (25 mph), post-speech buffer drops from 2.8 s to 2.1 s. Still better than baseline (1.5 s), but not by the full +1.3 s I claimed in §4.2. Verify the net effect is still a material improvement, and flag in the adversarial review if reviewers think further floor lift is warranted.

## 10. Dependencies and sequencing

- Issue 1 + Issue 2 touch the same function (`checkVoice`) and the same file. They MUST be sequenced: Issue 1 first (pure constant change), Issue 2 second (new helpers + text-forming amendments). Same PR.
- Issue 3 is orthogonal. Same PR for delivery cohesion, but commits sequentially after Issues 1 + 2 so a partial revert of the voice work doesn't drag in unrelated sidebar edits.
- Adversarial review runs on this v1 spec, surfaces MUST-FIX / SHOULD-FIX findings, produces v2. Writing-plans runs against v2.

## 11. Success criteria

Merge-to-main gate:

- All 4 field-test acceptance criteria pass on Cameron's Villa Rita → Costco re-drive.
- No regressions in the existing TTM v3 test suite.
- New tests (I12, I13, I14, BFCache structural) all green.
- Adversarial review landed (≥ 5 rounds, at least 1 Codex) with all MUST-FIX findings incorporated into spec v2.
- Plan review cycle (≥ 3 rounds) completed with no ambiguity or pitfall flags open.
