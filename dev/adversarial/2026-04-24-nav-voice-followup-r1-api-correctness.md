# Adversarial Review R1 — API / Correctness

**Spec under review:** [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md)
**Date:** 2026-04-24
**Agent:** pinyon-sub-r1
**Attack angle:** API / correctness — edit recipe bugs, invariant violations, semantic drift in `checkVoice`, order-of-operations, exception safety, BFCache idempotency under realistic event sequences.

---

### F1.1 — Missing `text.length > 0` guard lets chain-append emit a leading-comma malformed prompt

**Severity:** SHOULD-FIX

**Claim:** Spec §5.2 near-tier path retains the existing guard `if (text.length > 0) { uppercase }` but does NOT guard the chain-append block on `text.length > 0`. When Valhalla supplies an empty `verbal_pre_transition_instruction` and an empty `instruction`, base text is `""`, step-5 uppercase is skipped, step-6 prefix prepend is skipped (guarded). Then the chain-append block runs and executes:

```js
text = text.replace(/\.\s*$/, '') + chainJoin;   // text = "" + ", then in 400 feet, turn..."
```

Final `text` is `", then in 400 feet, turn right onto ..."` — a leading-comma fragment that TTS will pronounce as a sub-clause with no preceding clause. The downstream `if (!muted && text && onVoiceCb)` check will pass (text is truthy), so the malformed utterance will be spoken.

This is PRE-EXISTING behavior (the current code at line 436 has the same issue with `text = "" + ", then " + afterText`), but the amendment does not fix or acknowledge it, and the prefix-enabled near-tier makes the malformation MORE visible (added distance-phrase length makes the stray-comma opener more audible to the driver).

**Impact:** Low in practice — auto/bicycle profiles almost always have non-empty `verbal_pre_transition_instruction`. But the spec's G7 "no change in prompt count, prompt ordering, or chain-eligibility logic" implies the pre-existing shape is preserved, and a leading-comma utterance is objectively worse UX than a silent tick. A defensive guard costs one conditional.

**Recommendation:** Add an explicit guard in §5.2 near-tier chain-append:

```js
if (afterIdx < route.maneuvers.length && text.length > 0) {
  // ... existing chain-append ...
}
```

And note in §5.6 that I7's "never appended with empty next instruction" should be widened to also cover "never appended to empty base text." Consider adding I15: "when base near-tier text is empty, checkVoice emits no voice and does not mutate announcedSet[nearKey]/[farKey]." (Current code DOES mutate both markers even when text is empty, which is a separate latent bug worth acknowledging.)

---

### F1.2 — `announcedSet` marker mutations happen before prefix formatting, but nothing guards against `formatDistancePrefix` throwing partway through

**Severity:** SHOULD-FIX

**Claim:** Spec §5.2 near-tier orders operations as:
1. Compute `text` (strip, uppercase, prepend prefix — `formatDistancePrefix(distToNext, ...)` runs here)
2. Chain-append block (`formatDistancePrefix(distBetween, ...)` runs here, mutates `announcedSet[afterIdx+"-far"] = true` on success)
3. `announcedSet[nearKey] = true; announcedSet[farKey] = true;`

If `formatDistancePrefix` throws (e.g., spec's regex-lookup logic fails on a NaN distance, or `_geographicaUseImperial()` throws because `window` got mutated), one of three outcomes:

(a) Throw in step 1 `formatDistancePrefix(distToNext, ...)` — no markers set, voice not spoken. Next tick re-evaluates `nearWouldFire` (true, markers still unset) → same exception → same state → infinite retry.

(b) Throw in step 2 `formatDistancePrefix(distBetween, ...)` — no markers set (step-3 didn't run). Same infinite retry, never fires chain.

(c) Throw in `text.replace`, `charAt`, or `toLowerCase` (non-throwing in spec but defensive) — same story.

The symptom is NOT a lockout (the TTM v3 lockout concern in the task prompt) — markers stay UNSET, so the maneuver keeps being eligible to fire. But every tick spends CPU hitting the same exception, and no voice ever fires for this maneuver. The driver rolls past the turn in silence while `checkVoice` silently explodes each tick.

Contrast with the current production code: `text.charAt(0).toUpperCase() + text.slice(1)` is guarded by `text.length > 0`. If that branch were to throw for some reason, `announcedSet[nearKey] = true` would still run, marking the maneuver as announced and at least PREVENTING duplicate silent-failures on subsequent ticks. The spec's insertion of `formatDistancePrefix` in the voice-text pipeline changes the failure profile.

**Impact:** `formatDistancePrefix` itself is pure arithmetic + string formatting and should not throw under any realistic input. But the spec proposes it as a PUBLIC INTERFACE (exposed via `_geographicaNavEngineInternals`), inviting future amendments that could introduce hazards (locale-dependent number formatting, Intl API calls, etc.). The spec also relies on `_geographicaUseImperial()` which reads `window._geographicaUseImperial` — if a future refactor makes this a getter that throws, behavior degrades silently.

**Recommendation:** Either (a) wrap the prefix-formation in try/catch with a fallback to no-prefix text ("better to speak an un-prefixed prompt than no prompt"):

```js
var nearPrefix = "";
try { nearPrefix = formatDistancePrefix(distToNext, _geographicaUseImperial()); }
catch (e) { nearPrefix = ""; /* fall through to unprefixed */ }
```

or (b) move the `announcedSet[nearKey]=true; announcedSet[farKey]=true;` writes to BEFORE the prefix-forming block (mark-announced-then-compute-text order), so an exception in text formation at least prevents infinite retry. The existing D1-suppression semantics (marking farKey when nearKey fires) are preserved either way. Add a note in §5.6 I14: "prefix formation failures must not block `announcedSet` mutation."

I lean toward (b) — it matches the defensive posture in `applyReroute`'s re-tick (mark-then-emit) and makes the voice pipeline more forgiving.

---

### F1.3 — Net Issue-1 buffer gain is +0.6 s not +1.3 s, below the threshold the spec claims solves the symptom

**Severity:** SHOULD-FIX

**Claim:** Spec §4.2 presents a buffer table claiming a +1.3 s buffer gain at the 25 mph symptom speed (from 1.5 s to 2.8 s post-speech). Spec §9 (open questions for adversarial review) acknowledges the Issue-2 prefix ("In 1/4 mile, ") adds ~0.7 s of TTS, which means the NET post-speech buffer at 25 mph is 2.8 − 0.7 = 2.1 s, a gain of only +0.6 s over the current 1.5 s baseline.

But the field symptom Cameron reported was "prompt completes as the vehicle broaches the intersection" — i.e., ~0 s buffer. A +0.6 s gain brings this to ~0.6 s, which is still INSIDE the reaction-time envelope (human reaction to auditory turn-cue + actuation lag ≈ 0.8-1.5 s for an alert driver). The spec's G1 claim of "≥ 2.8 s of post-speech buffer" after Issue 1 is therefore not met once Issue 2 is composed on top.

Moreover, the +0.7 s prefix-cost estimate is for IMPERIAL + feet-band ("In 200 feet, "). For distances in the `[1000, 7920] ft` range (fractional miles), the prefix "In three quarters of a mile, " is ~1.0 s. The worst case for the symptom speed (25 mph ≈ 11.2 m/s) is the exact fire point — at 65 m distance the prefix says "In 200 feet, " (the short form). So the +0.7 s is correct for THIS symptom, but:

- At 30 mph (~13.4 m/s), fire point is 65 m → prefix = "In 200 feet, " → net buffer = (65/13.4) − 3 − 0.7 = 1.1 s. Baseline (no prefix, 50 m floor) was (50/13.4) − 3 = 0.7 s. Net gain +0.4 s.
- At 37 mph (floor boundary), fire point is 65 m → prefix adds 0.7 s cost → net buffer = 3.9 − 3 − 0.7 = 0.2 s. Baseline was 0 s. Net gain +0.2 s.

Spec §9 flags this as "still better than baseline (1.5 s), but not by the full +1.3 s I claimed in §4.2" but does NOT resolve it — the spec text in §4.2 still reads "+1.3 s delta." Leaving a known-wrong number in the spec body (with the correction buried in §9's open-questions) sets up the reviewer for confusion and invites a bad merge.

**Impact:** The whole point of Issue 1 is to buy post-speech buffer at the symptom speed. If the net gain is only +0.6 s, the spec has not delivered the G1 goal ("≥ 2.8 s of post-speech buffer"). Cameron re-drives Villa Rita → Costco with the symptom still present (just 0.6 s less severe), rejects the ship, and we burn a re-spec cycle.

**Recommendation:** Either (a) raise the auto floor further — 75 m buys 6.7 s / 3.7 s pre-speech, net 0.0 s (symptom), +1.3 s vs baseline after the 0.7 s prefix cost. 80 m buys 7.1 s / 4.1 s pre-speech, net 0.4 s symptom buffer, +1.7 s vs baseline. Cameron's stopping distance at 25 mph is ~40 ft (12 m); an 80 m floor still fires well before the stopping-distance envelope.

Or (b) acknowledge in §4.2 that the +1.3 s table is gross-of-prefix-cost and add a second column "net buffer after Issue 2 prefix cost" showing the real deltas. Update G1's "≥ 2.8 s" target to the net value (~2.1 s), and justify why 2.1 s is sufficient (cite driver-reaction literature: 1.5 s for expected, 2.5 s for unexpected stimuli; 2.1 s sits above the expected threshold and is a ship-acceptable compromise).

My recommendation is (a) — the floor is a simple constant, and the +1.3 s target was chosen for a reason. Lifting to 75 m restores the intended margin.

---

### F1.4 — `distBetween` uses the topological distance between maneuvers, but spec §5.4 Seg-0 example's chain-append prefix number is inconsistent with the fixture

**Severity:** SHOULD-FIX

**Claim:** Spec §5.4 table row:
> Seg 0 near+chain · fire @ 65 m, M2 @ 459 m | **In 200 feet**, turn left onto North 21st Avenue, **then in 1/4 mile**, turn left onto West Union Hills Drive

Reading this literally: near-tier fires at 65 m to M1; M2 is at 459 m from the driver's current position. The chain-append prefix in the spec's formulation uses `distBetween`, defined as `distanceToManeuver({segmentIndex: m.begin_shape_index, t:0}, afterIdx)` — which is the distance from M1's START to M2's START, NOT from driver's current position to M2.

If the driver is 65 m from M1 and M2 is 459 m from the driver, then `distBetween = 459 − 65 = 394 m ≈ 1293 ft ≈ 0.245 mi`. Per spec §5.1 bands: `[1000, 5/16=0.3125 mi)` → "In 1/4 mile, " — consistent with the row. So the number is correct but the reviewer-facing annotation "M2 @ 459 m" is the driver-to-M2 distance, not the M1-to-M2 distance. This is a documentation trap: a future maintainer reading the spec will see "M2 @ 459 m" and try to format 459 m as the prefix (459 m → 1506 ft → 0.285 mi → still "In 1/4 mile, "; same output, but by coincidence).

More worryingly, on Seg 4:
> Seg 4 near+chain · fire @ 65 m, M6 @ 117 m | **In 200 feet**, turn left onto North Black Canyon Highway, **then in 400 feet**, turn left onto West Wescott Drive

"M6 @ 117 m" — interpreting as driver-to-M6 distance, that's 117 m ≈ 384 ft → "In 400 feet, " ✓. Interpreting as M5-to-M6 distance (distBetween): if fire-at is 65 m from M5 and M6 is 117 m from driver, then distBetween = 117 − 65 = 52 m ≈ 171 ft → "In 200 feet, " ✗. The spec shows "400 feet" which only holds if "M6 @ 117 m" means M5-to-M6 topological distance (117 m = the spacing between the two maneuvers), not driver-to-M6.

So the spec IS using the topological (M5-to-M6) interpretation for §5.4, but the annotation "M6 @ 117 m" is ambiguous — does 117 m mean distance-from-driver or distance-from-M5?

**Impact:** The implementer and test authors will look at §5.4 as the spec's source of truth for expected prompt text. If they interpret "M6 @ 117 m" as distance-from-driver (the natural reading of "M6 at") and use `distToNext + (117 − distToNext) = 117` to compute, they'll produce the wrong prefix ("In 400 feet" is correct only if distBetween = 117; if distBetween is the DRIVER-to-M6 distance of 117, then the driver-to-M5 near-tier distance of 65 and the M5-to-M6 spacing of 52 would produce a "In 200 feet" chain-append). Test vectors derived from the table will be subtly wrong.

**Recommendation:** In §5.4, add a legend clarifying the annotation semantics:
> Column legend: "fire @ N m" = driver-to-current-maneuver distance at fire time. "Mi @ N m" = spacing between the two consecutive maneuvers (Mi−1 start to Mi start, same as `distBetween` in the code), NOT driver-to-Mi distance.

Also: add a test vector in §5.5 I13 that locks this in: "chain-append for fixtureVillaRitaCluster (30 m maneuver spacing) produces 'In 100 feet' prefix" — the test reveals whether the implementer used the topological or driver-relative semantics. (Spec §5.5 I13 line "assert near-tier text contains ', then in 100 feet, '" does this but implicitly; an explicit comment pinning "because distBetween = 30 m, not distToNext+30 m" would be clearer.)

---

### F1.5 — `verbal_multi_cue` / Valhalla's multi-cue chain in `verbal_pre_transition_instruction` can produce a double-stated distance if the trailing-"Then" strip misses

**Severity:** SHOULD-FIX

**Claim:** The existing near-tier strip at `navigation.js:413`:
```js
text = text.replace(/\.\s*Then\s+[^.]*\.?\s*$/i, '.');
```
removes the trailing `. Then <next maneuver>.` that Valhalla bakes into `verbal_pre_transition_instruction` for multi-cue maneuvers (`verbal_multi_cue: true` in Valhalla's maneuver object).

Consider the actual Valhalla shape the task prompt flags:
```
verbal_pre_transition_instruction = "Turn right onto 24th Drive. Then Turn left onto West Union Hills Drive."
```
- Step 2 strip: regex `/\.\s*Then\s+[^.]*\.?\s*$/i` — the `[^.]*` is non-greedy-ish over non-period characters. On `. Then Turn left onto West Union Hills Drive.` this matches `.\s*Then\s+Turn\s+left\s+onto\s+West\s+Union\s+Hills\s+Drive.` → replaced with `.` → residual = `"Turn right onto 24th Drive."` ✓
- Step 3 strip leading "Then ": no-op ✓
- Step 4 stripBakedDistance: no leading "In" → no-op ✓
- Prefix prepend: `"In 200 feet, turn right onto 24th Drive."` ✓

OK that case works. But consider a Valhalla shape with a distance INSIDE the chained suffix:
```
verbal_pre_transition_instruction = "Turn right onto 24th Drive. Then In 400 feet, Turn left onto West Union Hills Drive."
```
- Step 2 strip: `[^.]*` matches everything from ". Then " to the final `.` — but `In 400 feet,` contains no periods, so it's all one run of non-period characters. Match succeeds, strip to `"Turn right onto 24th Drive."` ✓

OK this also works — the strip is regex-based and chews through "In 400 feet" as part of the non-period run. Let me find a case where it fails.

What about a decimal in the distance?
```
verbal_pre_transition_instruction = "Turn right onto 24th Drive. Then In 1.5 miles, Turn left onto West Union Hills Drive."
```
- Step 2 strip regex: `\.\s*Then\s+[^.]*\.?\s*$`. The `[^.]*` is greedy by default (no `?`), matching as many non-period chars as possible. It reaches "In 1" and then hits the `.` in `1.5` — stops before it. Then the pattern needs `\.?\s*$` — optional period, optional whitespace, end-of-string. After `"In 1"` we have `".5 miles, Turn left onto West Union Hills Drive."` — `\.?` matches the `.`, then `\s*` expects whitespace-to-end. But we still have `5 miles, Turn left onto West Union Hills Drive.` — non-whitespace present, match fails.
- Regex backtracks: `[^.]*` matches `"In "`, then `\.?` matches nothing (empty), then `\s*$` — but there's "In 1.5 miles..." left — fails.
- Full regex match fails; no strip.
- Step 3 no-op, step 4 no-op (text starts with `Turn`, not `In`).
- Full text: `"Turn right onto 24th Drive. Then In 1.5 miles, Turn left onto West Union Hills Drive."`
- Uppercase step: T already capital.
- Prepend prefix: `"In 200 feet, turn right onto 24th Drive. Then In 1.5 miles, Turn left onto West Union Hills Drive."`

**The speech becomes**: "In 200 feet, turn right onto 24th Drive. Then In 1 point 5 miles, Turn left onto West Union Hills Drive." — the entire baked chain leaks through, including a distance phrase that's now stale (1.5 miles was Valhalla's route-planning distance, which may or may not match the driver's current topology).

This is Goal G8's exact concern: "When Valhalla bakes a distance into the source text ... we strip it before prepending the live distance, to avoid double-stating." But the existing trailing-"Then" strip regex is fragile against decimal distances.

**Impact:** On routes where Valhalla emits decimal miles in a chained suffix (any freeway-join maneuver beyond ~1.1 miles), the pre-existing strip misses and the driver hears a redundant Valhalla chain that's now duplicated with the new live-distance prefix. Field detectability: easy — any prompt where two "In X" phrases appear is a defect.

**Recommendation:** Update `BAKED_DISTANCE_RE` regex and the trailing-Then strip to handle decimals. Propose:
```js
// Trailing ". Then <anything ending with .>" — allow decimals inside the chain by
// using a more-permissive group that accepts non-period OR a period followed by digit.
text = text.replace(/\.\s*Then\s+(?:[^.]|\.(?=\d))*\.?\s*$/i, '.');
```

Also add test vectors to §5.5 for decimal-containing chained suffixes:
```
"Turn right onto 24th Drive. Then In 1.5 miles, Turn left onto Union Hills."
  → expected near-tier text: "In 200 feet, turn right onto 24th Drive."
"Turn right. Then In 0.3 miles, Bear left."
  → expected: "In 200 feet, turn right."
```

And the adjacent case where Valhalla bakes a decimal in the LEADING form:
```
verbal_pre_transition_instruction = "In 1.5 miles, Merge onto I-5."
```
Current stripBakedDistance regex: `^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|...)\s*,\s*(?=[A-Z])`. The `[a-zA-Z0-9.\s]+?` IS non-greedy, so it'll try shortest-first. Match: `^In\s+` = `In `, then `[a-zA-Z0-9.\s]+?` starts at `1`, non-greedy → tries `1`, then `\s(?:mile...)` — next char is `.`, not `\s` → fails. Backtrack: tries `1.` → next char is `5`, not `\s` → fails. Eventually matches `1.5` → next char is `\s` → then `miles` → then `,` → then `(?=[A-Z])` → works. ✓

OK `stripBakedDistance` IS resilient to decimals. But the trailing-Then strip is not. Both paths need the same decimal-awareness.

---

### F1.6 — BFCache restore before DOMContentLoaded: idempotency claim holds, but `initSidebarTabs()` click handlers must be attached before the `pageshow` listener's `.click()` fires, and the spec's "module-scope" placement does not enforce this ordering

**Severity:** SHOULD-FIX

**Claim:** Spec §6.2:
> The listener is placed at module scope, outside DOMContentLoaded, so it wires up immediately during script parsing — not dependent on DOMContentLoaded having fired.

And:
> `restoreLastSidebarTab()` is idempotent via early-return when target tab already has `.active`.

Scenario: the HTML page is parsed, `app.js` is parsed, `window.addEventListener('pageshow', ...)` is registered. DOMContentLoaded has NOT yet fired. At this point, `initSidebarTabs()` has not run — tab `click` handlers are NOT yet wired. Now suppose the browser dispatches `pageshow` with `e.persisted === true` BEFORE DOMContentLoaded.

Per the HTML spec, `pageshow` fires after page-load event (after DOMContentLoaded + window.load). So this sequence shouldn't happen on a fresh load. BUT on BFCache-restore, the page has ALREADY fully loaded previously. BFCache fires `pageshow` with persisted=true without running DOMContentLoaded again. However, BFCache ALSO preserves the previously-registered event listeners, so the click handlers wired by `initSidebarTabs()` on the first-ever load are still live.

This is fine for the normal case. But consider a subtle failure mode: if the first load NEVER completed `initSidebarTabs()` (e.g., a prior script threw and broke the bootstrap, but the browser still BFCached the partially-initialized page), pageshow.persisted=true fires, `restoreLastSidebarTab()` runs, finds `targetTab`, does `.click()` — which dispatches a click event but NO handler is attached. The click has no effect. User is on wrong tab, no error.

More importantly, the spec's §6.2 claim "wires up immediately during script parsing — not dependent on DOMContentLoaded having fired" is technically true but MISLEADING. The `pageshow` LISTENER is wired early, but the STATE it depends on (click handlers wired by `initSidebarTabs`) is still DOMContentLoaded-scoped. The two are decoupled but practically coupled: if DOMContentLoaded never completes, the pageshow path fails silently.

Related: the spec places the pageshow listener AT MODULE SCOPE. The IIFE wrapper `(function () { ... })();` at the top of `app.js` (need to verify) — if the pageshow listener is inside the IIFE's module scope, it IS registered at script-parse time. If placed after the IIFE (at true module/global scope) it's still at parse time but lacks access to `restoreLastSidebarTab` (which is IIFE-private). The spec's code snippet uses `restoreLastSidebarTab()` bare, implying IIFE-internal scope. This is correct, but the spec should explicitly state the placement to prevent a "put it at global scope" misinterpretation.

**Impact:** Low-probability correctness hit on BFCache restores after a broken first-load. Higher-probability is a future refactor moving the pageshow listener to global scope and breaking the reference to `restoreLastSidebarTab`.

**Recommendation:** Tighten §6.2:

> Place the pageshow listener at the END of the DOMContentLoaded callback, AFTER `restoreLastSidebarTab()` has fired once synchronously. This ensures all click handlers are wired before any future BFCache restore can invoke `restoreLastSidebarTab()` via the pageshow path. The first-load tab restoration comes from the DOMContentLoaded call; BFCache restorations thereafter come from the listener.

```js
document.addEventListener('DOMContentLoaded', function () {
  initMap();
  // ... all other init ...
  initAdmin();
  restoreLastSidebarTab();
  // ... rest of DOMContentLoaded ...

  // AFTER initSidebarTabs() + initAdmin() have wired click handlers:
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) restoreLastSidebarTab();
  });
});
```

This trades "listener wired at parse time" (no practical benefit; pageshow on the FIRST pageshow event after parse-completion fires after DOMContentLoaded anyway per HTML spec) for "listener invocation always sees a fully-initialized DOM." Also update §6.4's invariants to codify the ordering.

---

### F1.7 — Admin-tab polling timer leaks on BFCache restore when the polling tab WAS admin before backgrounding

**Severity:** SHOULD-FIX

**Claim:** `initAdmin()` at `app.js:3721` wires two click-side effects:
1. Admin tab click → `fetchAdminStatus(); clearInterval(adminTimer); adminTimer = setInterval(fetchAdminStatus, ADMIN_REFRESH_MS);`
2. Non-admin tab click → `clearInterval(adminTimer); adminTimer = null;`

Consider: user is on Admin tab when the app backgrounds. BFCache preserves the running `setInterval` (adminTimer). Resume via BFCache: pageshow.persisted=true fires. `restoreLastSidebarTab` reads localStorage `'admin-panel'`, finds Admin button, checks `!classList.contains('active')` → FALSE (BFCache preserved the active state). Early-returns. adminTimer continues running. ✓ Good.

Now consider: user is on Admin when backgrounded. BFCache restore fires pageshow.persisted=true. But between backgrounding and resume, iOS background-throttling killed the setInterval callback. When BFCache restores, setInterval is... per spec, BFCached timers resume on restore (Chromium v88+, Safari 15+). So timer continues firing post-restore.

BUT: what if BFCache restored state is different from user-intended? E.g., user was on Route tab, backgrounded (adminTimer=null, Route active in DOM). App evicted from BFCache, full reload fires DOMContentLoaded. Static HTML has Layers active. `restoreLastSidebarTab` finds localStorage='route-panel', calls Route.click() → initSidebarTabs handler runs, Route becomes active. Route's click handler (in initAdmin's other-tabs registration) clears adminTimer (was already null, no-op). ✓

What if user switches tab DURING the pageshow sequence? Unlikely but the spec should have a think.

The subtle concern: `initAdmin()` registers non-admin-tab click handlers to clear the timer. But ALSO `initSidebarTabs` registers click handlers on ALL tabs. On a `.click()` call, BOTH sets of handlers fire (they're registered on the same element). Order: order of `addEventListener` calls. `initSidebarTabs` is called first in DOMContentLoaded, then `initAdmin` — so `initSidebarTabs`'s click handler runs first (sets active class, writes localStorage), then `initAdmin`'s click handler (clears admin timer for non-admin). ✓ OK.

But the REAL bug is subtler. Spec §6.2 places the pageshow listener OUTSIDE DOMContentLoaded. If a BFCache restore fires before `initAdmin()` has ever run (impossible for BFCache because BFCache implies prior complete load, but let's consider unloaded-prefetch)... actually this is fine.

Hmm let me look for a real issue. Consider: user is on Admin when backgrounded. iOS aggressively evicts from BFCache (memory pressure). User returns; browser does NOT BFCache-restore (evicted); full reload. DOMContentLoaded fires, static HTML has Layers active. `initAdmin()` wires handlers. `restoreLastSidebarTab()` reads localStorage='admin-panel', clicks Admin tab → initSidebarTabs handler activates Admin panel. initAdmin handler fires `fetchAdminStatus(); clearInterval(null); adminTimer = setInterval(...)`. ✓

Now consider: BFCache restores and the Admin tab was NOT previously active (user was on Route). Spec §6.2 pageshow listener fires, calls `restoreLastSidebarTab()`. localStorage='route-panel' (matching what DOM already shows). `!targetTab.classList.contains('active')` = FALSE → early-return. adminTimer remains null. ✓

Now the SPECIFIC BUG: user was on Admin, backgrounded, BFCache restores and admin timer was already running. pageshow fires. `restoreLastSidebarTab` sees Admin already active → early-returns. adminTimer keeps running. Good.

But wait — what if Admin is in localStorage but NOT active in DOM post-BFCache-restore? This requires BFCache to NOT preserve the .active class, which contradicts the whole BFCache model. UNLESS the page was evicted and fully reloaded — but then pageshow.persisted would be FALSE, not true, and the listener early-returns via `e.persisted`.

OK so in the model the spec proposes, there's no adminTimer leak from the idempotency-bypass path. The existing behavior is sound.

BUT — here's the gotcha: `restoreLastSidebarTab` only early-returns when the target tab is already active. What if both target tab and current tab are Admin, and `adminTimer` is nevertheless NULL (because iOS terminated the BFCached interval)? Then the Admin tab is visually active but no polling is running. pageshow fires → restoreLastSidebarTab checks active → TRUE → early-returns → polling stays DEAD. The user sees Admin tab active but the service status never refreshes.

This is an existing bug UNRELATED to this spec, but the spec's pageshow path doesn't fix it — and the spec claims "reopening the sidebar after any iOS Safari BFCache restore-event produces the tab that was active before the backgrounding, matching the user expectation" (G9). User expectation might be stronger: "the tab AND its live data." If Admin polling is dead post-BFCache, G9 is weakly satisfied.

**Impact:** On Admin tab specifically, BFCache restore may leave the tab cosmetically correct but with dead polling. User sees stale status. Low severity for non-active-users; confusing for Cameron if he tries to monitor a running data pipeline from a backgrounded-then-restored app.

**Recommendation:** In §6.2, add a deliberate "force re-click if admin-panel is the target, even if already active" path, to re-wake polling:

```js
window.addEventListener('pageshow', function (e) {
  if (e.persisted) {
    restoreLastSidebarTab();
    // iOS may kill BFCached setIntervals. Re-wake admin polling if admin is active.
    var activeTab = document.querySelector('.tab-btn.active');
    if (activeTab && activeTab.dataset.panel === 'admin-panel') {
      // Dispatch a click to re-trigger fetchAdminStatus + fresh setInterval.
      activeTab.click();
    }
  }
});
```

But `activeTab.click()` when already-active triggers the initSidebarTabs handler again (no-op since already active), AND the initAdmin handler (restarts polling). Verify with a manual iOS BFCache test.

Alternatively, split the concern into a separate issue and only ship the bare BFCache fix now with a TODO noting the adminTimer-BFCache-eviction case for a future patch. Spec §6.4 should document the limitation.

---

### F1.8 — Spec §5.2 chain-append uses `route.maneuvers[afterIdx].instruction` (not `verbal_pre_transition_instruction`), which inherits a pre-existing inconsistency that the stripBakedDistance addition amplifies

**Severity:** NICE-TO-HAVE

**Claim:** Existing line 432: `var afterText = route.maneuvers[afterIdx].instruction || "";` — uses the `instruction` field, not the `verbal_pre_transition_instruction`. The Valhalla `instruction` field is the on-screen banner text (compact, written-English-oriented), while `verbal_pre_transition_instruction` is optimized for TTS (expanded abbreviations, explicit punctuation).

Spec §5.2 preserves this: `var afterText = stripBakedDistance(route.maneuvers[afterIdx].instruction || "");`.

Issue: Valhalla's `instruction` field rarely has a leading distance prefix (banner text assumes the distance is in a separate UI element), but Valhalla's `verbal_pre_transition_instruction` DOES sometimes have a leading distance. By using `instruction` for chain-append, the spec gets TTS-suboptimal text with no baked distance to strip — `stripBakedDistance` is a no-op here in practice. Wasted call but not harmful.

The real concern: the chain-appended text is in TTS flow (it IS spoken), so using the `instruction` field gives the driver non-TTS-optimized text. E.g., `instruction: "Turn left onto I-5 N"` — TTS pronounces "eye five en" — vs `verbal_pre_transition_instruction: "Turn left onto Interstate 5 North"`. The driver's chain-heard cue is harder to parse than the same maneuver's own near-tier (which uses verbal_pre_transition).

**Impact:** Cosmetic TTS quality in the chain-append. User-audible only on abbreviation-heavy maneuvers (highway joins, numbered routes).

**Recommendation:** Update §5.2 chain-append to prefer `verbal_pre_transition_instruction`:

```js
var afterText = stripBakedDistance(
  route.maneuvers[afterIdx].verbal_pre_transition_instruction ||
  route.maneuvers[afterIdx].instruction ||
  ""
);
```

And note in §5.6 invariants (or spec prose): "chain-append now uses the TTS-optimized verbal_pre_transition_instruction where available, consistent with the near-tier base text selection."

Explicitly flag as a change from prior behavior if the spec wants to preserve the status quo; otherwise take the quality improvement.

---

### F1.9 — Capitalization inconsistency in chain-append without prefix: ", then Turn" vs ", then in 400 feet, turn"

**Severity:** NICE-TO-HAVE

**Claim:** Spec §5.2 chain-append code produces:
- With prefix: `", then in 400 feet, turn left..."` (lowercase "then" + lowercase prefix + lowercase instruction start)
- Without prefix (sub-cutoff distance): `", then Turn left..."` (lowercase "then" + CAPITALIZED instruction start)

The two produce visually and audibly jarring inconsistency within a single near-tier + chain utterance. The spec's justification (§5.2 comment):
> When no prefix applies, preserve the existing capital-first behavior ... capitalized second clause matches the current ship.

But the "current ship" is what Cameron is asking to CHANGE (Issue 2). Preserving a cosmetic inconsistency because it's the status quo seems orthogonal to a spec that's overhauling the presentation. TTS pronunciation of "then Turn left" vs "then turn left" is identical for most voices (no pause inserted for mid-sentence capitals), but the written test vectors will surface the inconsistency confusingly.

**Impact:** Test-vector confusion; no auditory impact. Minor maintenance friction ("why does the test expect different casing for with-prefix vs without-prefix chain?").

**Recommendation:** Normalize: always lowercase the chain-clause's first letter (regardless of prefix presence):

```js
var afterFirstLower = afterText.charAt(0).toLowerCase() + afterText.slice(1);
if (afterPrefix) {
  var lcPrefix = afterPrefix.charAt(0).toLowerCase() + afterPrefix.slice(1);
  chainJoin = ", then " + lcPrefix + afterFirstLower;
} else {
  chainJoin = ", then " + afterFirstLower;
}
```

Output: `", then turn left..."` in both cases. Matches the "X, then Y" prosody. Update §5.4 table and §5.5 tests accordingly.

---

### F1.10 — Spec §5.5 test vector for `formatDistancePrefix(290, true)` is numerically wrong and will fail the test suite

**Severity:** MUST-FIX

**Claim:** Spec §5.5:
> `formatDistancePrefix(290, true) === "In 1000 feet, "` (951.4 ft, still in feet band since < 1000 ft, rounds to 1000).

Computing: 290 m × 3.28084 ft/m = 951.4436 ft. The spec's feet-band definition is `[100, 1000) ft: "In N00 feet, " (rounded to nearest 100)`. So 951.4 ft falls in this band.

Rounding 951.4 to the nearest 100: `Math.round(951.4 / 100) * 100 = Math.round(9.514) * 100 = 10 * 100 = 1000`. Output: `"In 1000 feet, "`. ✓ Math checks out.

BUT: 951.4 is ≥ 950, so it rounds UP to 1000, landing at exactly the band boundary. The next test vector:
> `formatDistancePrefix(305, true) === "In 1/4 mile, "` (1000.66 ft = 0.1895 mi)

1000.66 ft is in the `[1000, 5/16 mi)` band → "In 1/4 mile, ". But 305 m × 3.28084 = 1000.66 ft. Let me verify: 305 × 3.28084 = 1000.656 ft. Yes, just over 1000 ft.

So at 290 m (951 ft) → "In 1000 feet, " and at 305 m (1001 ft) → "In 1/4 mile, ". There's a 15 m gap between the two cases. What about 298 m (977.5 ft, rounds to 1000) → "In 1000 feet, ". And 301 m (987.9 ft, rounds to 1000) → still "In 1000 feet, ". And 305 m (1000.66 ft) → "In 1/4 mile, ". The transition from "1000 feet" utterance to "1/4 mile" utterance happens between 302 m (991 ft, rounds to 1000) and 305 m (1001 ft, into 1/4-mile band).

**This means two adjacent 1 Hz GPS ticks at 25 mph (~11.2 m/s → 3.5 m between ticks) CAN cross this boundary in a single tick.** Driver hears "In 1000 feet" on one tick and (if the announcement re-fires) "In 1/4 mile" on the next. Since `announcedSet` latches, this only matters if the near-tier hasn't fired yet. But across a single approach, the driver hears either "In 1000 feet" OR "In 1/4 mile" — not both — so no user-visible defect.

HOWEVER, spec §5.5 says 290 m → "In 1000 feet, ". But then the spec's own fractional-miles band definition uses miles-based arithmetic: `1000 / 5280 = 0.18939 mi`, which falls in `[0.1875=3/16, 0.25=1/4)`. There's no `[0.1875, 0.25)` band defined in §5.1 — the first mile-band is `[1000/5280, 5/16) = [0.1894, 0.3125)`. Is the feet → miles transition at EXACTLY 1000 ft? §5.1 says `[100, 1000) ft: "In N00 feet, "` (note: `1000` is EXCLUDED) and `[1000, 5/16 mi) ft: "In 1/4 mile, "` (note: `1000` is INCLUDED).

So 951.4 ft (290 m): is it in `[100, 1000)` or not? 951.4 < 1000 → YES, it's in the feet band. Rounds to 1000. Output: "In 1000 feet, ".

But WAIT — the rounding is round-to-nearest-100, which for 951.4 gives 1000. But the band condition `[100, 1000)` applies to the INPUT value (951.4 ft), not the ROUNDED output (1000 ft). So 951.4 ft is definitively in the feet band, and we report 1000 feet. The test vector `"In 1000 feet, "` is correct — IF AND ONLY IF the implementer's code applies the band-check to the INPUT feet and rounds separately, rather than rounding first then band-checking.

If the implementer writes:
```js
var ft = meters * 3.28084;
var roundedFt = Math.round(ft / 100) * 100;
if (roundedFt < 1000) return "In " + roundedFt + " feet, ";
else if (...) // fractional miles
```

then 951.4 ft → roundedFt = 1000 → `roundedFt < 1000` is FALSE → falls through to fractional miles → "In 1/4 mile, " NOT "In 1000 feet, ". **Test vector fails.**

If instead they write:
```js
var ft = meters * 3.28084;
if (ft < 1000) return "In " + (Math.round(ft / 100) * 100) + " feet, ";
else if (...) // fractional miles
```

then 951.4 ft → `ft < 1000` is TRUE → rounds to 1000 → "In 1000 feet, ". ✓

The spec does NOT pin the implementation order. The test vector will fail under the first (natural, Google-like) implementation. The spec's own prose in §5.5 acknowledges the quirk: "the feet-band max of 999.9 ft never rounds to 1000 because anything ≥ 950 ft but < 1000 ft rounds to 1000" — this is SELF-CONTRADICTORY phrasing ("max is 999.9 ft ... rounds to 1000"). The intent seems to be the second implementation, but the prose is muddled.

**Impact:** The implementer will write the natural first form (round-then-band), and the test vector 290 m → "In 1000 feet, " will fail. Writing-plans will then have to re-decide: fix the test expectation to "In 1/4 mile, " OR fix the implementation to band-first-round-second. Ambiguity left for plan-writer to resolve is a known pitfall.

**Recommendation:** Decide NOW in the spec:

**Option A (pin implementation)**: State in §5.1: "Band check is performed on the raw input distance BEFORE rounding. The rounding is cosmetic — it does not promote a value to the next band. 951.4 ft is in the feet-band, rounds to 1000 for display, output is 'In 1000 feet, '."

**Option B (pin output)**: Drop the 290 m test vector; replace with a clean case (e.g., 250 m = 820 ft, rounds to 800, output "In 800 feet, ") that doesn't hit the band boundary. Forbid the "In 1000 feet, " output by reducing the feet-band upper bound to 949.9 ft and making 950 ft → "In 1/4 mile, " the start of mile bands (but this breaks the 305 m test vector too).

Option A is cleaner and matches the spec's internal intent. Pin it explicitly. Also fix the muddled §5.5 prose to read "the feet-band outputs range from '100 feet' to '1000 feet' — the latter fires for any input in [950, 1000) ft which rounds up to 1000." Remove "never rounds to 1000."

This is a MUST-FIX because an ambiguous test vector will cause a test failure that blocks ship.

---

### F1.11 — BAKED_DISTANCE_RE over-matches "In 1/4 mile, " generated by the new formatDistancePrefix itself, creating an accidental idempotency constraint

**Severity:** NICE-TO-HAVE

**Claim:** The spec's `stripBakedDistance` regex `^In\s+[a-zA-Z0-9.\s]+?\s(?:feet|foot|mile|miles|meters?|kilometers?|km|m)\s*,\s*(?=[A-Z])` matches both Valhalla's baked "In 400 feet, " AND the new `formatDistancePrefix` output "In 200 feet, " / "In 1/4 mile, " (well, "1/4" contains `/` which is NOT in the character class — let's verify).

Regex char class: `[a-zA-Z0-9.\s]` — only letters, digits, period, whitespace. Forward slash is NOT included. So `formatDistancePrefix(500, true) = "In 1/4 mile, "` will FAIL `stripBakedDistance`'s regex due to the `/` character. Good — the new distance prefixes don't accidentally match and get stripped.

BUT: the feet-band output "In 200 feet, " DOES match the regex (all chars in the class). So if the pipeline somehow runs `stripBakedDistance` on text that already has a `formatDistancePrefix`-generated prefix, it'll strip the prefix. Normally this doesn't happen — `stripBakedDistance` runs before `formatDistancePrefix` in the spec's §5.2 flow. But consider the chain-append:

```js
var afterText = stripBakedDistance(route.maneuvers[afterIdx].instruction || "");
```

This strips baked distances from `instruction`. Fine. But what if `instruction` was written by Valhalla to include "In 1/4 mile, Turn..."? Check: `instruction` usually does NOT have a distance prefix (it's banner text), but SOME Valhalla versions DO emit "In N feet, Turn..." in `instruction` for the first maneuver. Regex matches, strips, OK.

The spec's idempotency CONSTRAINT is implicit: `stripBakedDistance(stripBakedDistance(x)) === stripBakedDistance(x)`. Verify: after one strip, the residual starts with a capital letter, NOT with "In ". Regex requires `^In\s+` at the start. Residual fails the match. Second strip is a no-op. ✓ Idempotent.

But consider a pathological case: `"In 500 feet, In 200 feet, Turn left."` — either a doubly-baked or a bug. First strip: matches `"In 500 feet, "` (lookahead sees `I` from the second "In" — wait, `I` is a capital. Lookahead `(?=[A-Z])` requires A-Z; `I` qualifies. Match succeeds.) → residual = `"In 200 feet, Turn left."`. Second strip would match again: `"In 200 feet, "` → residual = `"Turn left."`. But spec only runs strip ONCE.

**Impact:** Extremely unlikely to encounter doubly-baked Valhalla text in the wild. But if someone refactors the pipeline to add a safety-net "re-strip after prefix" pass (e.g., to guarantee no duplicate "In" phrases), the new formatDistancePrefix output would be accidentally stripped. Latent fragility.

**Recommendation:** Add a test vector to §5.5:
```
stripBakedDistance("In 500 feet, In 200 feet, Turn left.") === "In 200 feet, Turn left."
  // single pass; pipeline must not re-invoke stripBakedDistance after prefix prepend.
```

And an invariant in §5.6: "Exactly one `stripBakedDistance` pass per voice-text construction. Multiple passes would strip the pipeline's own live-distance prefix."

Also: consider whether `formatDistancePrefix` should emit text that's GUARANTEED non-matchable by `stripBakedDistance`. E.g., use "At" instead of "In" for the live prefix, or use a non-breaking space, or include a character outside `[a-zA-Z0-9.\s]`. Overkill for now; document the invariant and move on.

---

## Summary

- **MUST-FIX: 1** (F1.10 — 1000 ft band-boundary test vector ambiguity blocks ship)
- **SHOULD-FIX: 6** (F1.1 empty-text chain leading-comma; F1.2 prefix throw infinite-retry; F1.3 Issue-2 prefix cost eats Issue-1 buffer; F1.4 distBetween semantics ambiguous in §5.4 annotation; F1.5 decimal-mile chain strip miss; F1.6 pageshow-before-DOMContentLoaded init ordering; F1.7 admin polling stays dead after BFCache timer eviction)
- **NICE-TO-HAVE: 3** (F1.8 chain-append uses wrong Valhalla field; F1.9 chain-clause capitalization inconsistent; F1.11 stripBakedDistance + formatDistancePrefix implicit idempotency constraint)

F1.3 and F1.10 together imply a spec v1.1 revision before plan-writing: one to re-tune the floor and commit on the buffer claim, one to pin the band-boundary rounding semantics.

F1.6 and F1.7 deserve consideration together: the BFCache path has three distinct sub-cases (persisted + DOM-synced, persisted + DOM-desynced, non-persisted) and §6.2-6.4 elide them. A brief sub-case table in §6 would close the ambiguity.
