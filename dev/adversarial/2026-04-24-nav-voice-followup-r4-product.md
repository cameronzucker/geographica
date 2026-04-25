# Adversarial review R4 — product + UX lens

**Agent:** pinyon-sub-r4
**Date:** 2026-04-24
**Spec under review:** [docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md](../../docs/superpowers/specs/2026-04-24-nav-voice-followup-design.md) v1
**Attack angle:** Does the spec actually solve Cameron's field problem? Does it introduce new UX regressions (speech overruns, chopped audio, information overload, parity drift)? Does the sidebar fix honor user intent on BFCache restore?
**Scope boundary:** No re-litigation of R1 (API correctness), R2 (concurrency), or R3 (testing).

---

### F4.1 — Issue 1 buffer lift is mathematically under-specified: prefix eats most of the gain, net improvement at symptom speed is under 1 s post-speech

**Severity:** MUST-FIX

**Claim:** §4.2 advertises "+1.3 s of post-speech buffer at 25 mph." §9 admits the prefix adds ~0.7 s of speech. Actual net at the symptom speed is **+0.6 s post-speech**, not +1.3 s. Worse, this is a *mean*-case estimate; for users who selected a slow voice from the voice-picker (see F4.9), the prefix can consume the entire lift and leave them worse than today.

Speech-timing math (verifiable against typical Web Speech API `rate=1.0` en-US voices):

- "Turn right onto Black Canyon Highway" — ~8 syllables of content + 3 syllables Canyon + 2 syllables High·way ≈ 13 syllables ≈ 2.6 s at 5 syl/s (Samantha-class fast voice) or ~3.5 s at 3.7 syl/s (slow iOS male default).
- "In 200 feet, turn right onto Black Canyon Highway" — +4 syllables ("In·two·hun·dred·feet" collapses to ~4 syl in fluent TTS) ≈ +0.8 s fast / +1.1 s slow.

Post-speech buffer at 25 mph (11.2 m/s), fire at 65 m:
- Time-to-intersection from fire: 65 / 11.2 = 5.8 s.
- Prefixed utterance: fast voice 2.6 + 0.8 = 3.4 s speech → **2.4 s post-speech**. Slow voice 3.5 + 1.1 = 4.6 s speech → **1.2 s post-speech**.
- Baseline (today, 50 m floor, no prefix): 50/11.2 = 4.5 s − 3.0 s speech = 1.5 s post-speech.

**Net improvement for a slow-voice user: 1.2 − 1.5 = −0.3 s. Spec makes it WORSE for that cohort.**

**Impact:** Cameron explicitly said he wants "+1 s of additional notice." The spec, as written, delivers less than +1 s mean-case and negative improvement to slow-voice users — a silent regression on the exact symptom Issue 1 is trying to fix. §9 already flagged this risk ("still better than baseline (1.5 s), but not by the full +1.3 s"), but the spec did not adjust the floor value in response. Shipping this without a larger lift means the next field drive will still produce "broaches the intersection" reports, *and now also* a pull-request comment from Cameron asking why the promised buffer didn't materialize.

**Recommendation:** Lift `VOICE_DISTANCE_FLOOR.auto` to **75 m** (not 65 m) and `bicycle` to **45 m**. Math at 75 m / 11.2 m/s = 6.7 s − 4.6 s slow-voice prefixed speech = **2.1 s post-speech** (vs 1.5 s baseline = +0.6 s net for the worst-case voice), or −3.4 s fast-voice = **3.3 s post-speech** (= +1.8 s net for fast voice). At the worst end this still delivers positive improvement; at the best end it exceeds Cameron's ask. Add a buffer-math table in §4.2 that models BOTH a fast-voice (2.5 s no-prefix, 3.3 s prefixed) AND a slow-voice (3.5 s no-prefix, 4.6 s prefixed) row, explicitly, for each speed — not just a single "~3 s typical." The single-speech-time assumption is the root of this finding.

Alternative if a larger floor lift is rejected for highway-regression reasons (it shouldn't — at 37 mph floor is inactive, TTM governs): adopt an *adaptive* floor where the 65 m value is used only when `formatDistancePrefix` returns empty (i.e., short-hop parking-lot turns, where no prefix speech is incurred), and 75 m when a prefix will be prepended. That's a 2-line code change for 10 m of worst-case cushion.

---

### F4.2 — Chain-append utterance at 65 m is likely to complete AFTER the first intersection is crossed

**Severity:** MUST-FIX

**Claim:** Spec §5.4 shows the post-reroute Villa Rita prompt as "In 200 feet, turn left onto North 21st Avenue, then in 1/4 mile, turn left onto West Union Hills Drive." Count the syllables:

- "In·two·hun·dred·feet·turn·left·on·to·North·twen·ty·first·Av·e·nue·then·in·a·quar·ter·mile·turn·left·on·to·West·Un·ion·Hills·Drive" ≈ **30 syllables**.
- At 5 syl/s (fast): 6.0 s. At 3.7 syl/s (slow): 8.1 s.

At 25 mph (11.2 m/s), 6.0 s of speech = 67 m; 8.1 s = 91 m of travel. The near-tier fires at 65 m. **The driver reaches the 21st Avenue intersection before the utterance finishes — for ANY voice speed.**

This is worse than current: today's Villa Rita prompt "Turn left onto North 21st Avenue, then turn left onto West Union Hills Drive" is ~18 syllables ≈ 3.6 s fast / 4.9 s slow, which at 50 m floor / 25 mph (4.5 s to intersection) already is a close call for the slow voice but survives for the fast voice. **The spec's chain utterance busts the budget for both.**

**Impact:** This is the exact complaint Cameron filed ("prompts fire as the vehicle broaches the intersection"), now *introduced by the fix* for chain-append turns. Villa Rita → Costco has two chain-append sites (§5.4 Seg 0, Seg 4); both will now audibly end with the driver already inside the turn. Issue 2 promises "every prompt carries a live-distance prefix" but implicitly assumes prompt duration was negligible; the Villa Rita chain case proves it isn't.

Worse: `nav-ui.js:496` calls `speechSynthesis.cancel()` before every new utterance. If the second maneuver's far-tier (or any subsequent prompt) fires while the chain utterance is still speaking — which, at 6-8 s speech duration and 3 s near-tier window, is almost guaranteed — the driver hears the chain clipped mid-word. See F4.5.

**Recommendation:** Add a §5.4 bullet that explicitly computes expected utterance duration for each prompt in the Villa Rita table, using both a fast and slow voice model (e.g., `utteranceSeconds = syllableCount / syllablesPerSecond`). Flag any cell where `utteranceSeconds > (fireDistance / expectedSpeed)` as a regression. For chain-append specifically, either:

(a) **Shorten chain-append prefixes.** "Turn left onto 21st, then 1/4 mile to Union Hills" (drop the inner "in" and the second "turn left onto" — the driver knows it's a turn because the first maneuver mentioned it). ~20 syllables instead of 30.

(b) **Compute a max-utterance-budget from TTM** and drop the chain-append entirely when the budget won't cover both maneuvers. In the Villa Rita case: 65 m / 11.2 m/s = 5.8 s budget; fast-voice single-maneuver prefixed = 3.4 s; chain adds 2.6-5.0 s more → only include chain if `(budget − primarySpeech) > chainSpeech`. The existing `distBetween <= NEXT_AFTER_NEXT_DISTANCE` gate is not speed-aware; this would make it so.

(c) **Stop prefixing the chain-append's distance.** "Turn left onto 21st, then turn left onto Union Hills" (14 syllables). Drops 6 syllables = ~1.5 s of speech at the cost of losing the secondary-maneuver distance. Cameron's Issue 2 motivation was "driver with eyes-on-road can't disambiguate" — but the chain-append's "then" already signals relative imminence, and the primary prefix already sets up the interval. Parse the cost/benefit and commit.

My strong vote: (a) + (b) combined. Spec should pick one before landing.

---

### F4.3 — Speech cancellation race during chain-append + reroute produces "half-info" outcomes

**Severity:** SHOULD-FIX

**Claim:** `onVoice` at `nav-ui.js:494-506` calls `speechSynthesis.cancel()` unconditionally before every `speak()`. If the chain utterance ("In 200 feet, turn left onto 21st, then in 1/4 mile, turn left onto Union Hills") is 6-8 s long, and the driver executes the first maneuver promptly (reasonable at 25 mph with a 5.8 s budget), the engine advances `currentManeuverIdx` past maneuver 1 to maneuver 2. On the very next tick, `checkVoice` may fire the *next* chain — OR a reroute callback may fire "Rerouting..." — while the first chain is still speaking. Cancel fires; driver hears: "In two hundred feet, turn left onto twenty-fi—" *[silence]* *[new utterance]*.

The current (pre-spec) behavior has this race too, but with shorter utterances (14 syllables vs 30), the window is ~3.6 s instead of ~6-8 s. **Doubling the utterance length doubles the probability of mid-utterance cancellation.**

**Impact:** Eyes-free driver hears "In two hundred feet, turn left onto twenty-fi—" and doesn't know whether the turn is at 21st, 22nd, or 25th Avenue. Worse than today's truncated "Turn left onto twenty-fi—" because today's utterance starts with the actionable instruction ("Turn left"), while the spec's starts with 3 syllables of prefix before the driver knows this is even a turn instruction. **The prefix actively delays the eyes-free-critical information.**

**Recommendation:** Two options, pick one:

(a) **Preserve the "turn <direction>" lede.** Instead of "In 200 feet, turn left onto X", emit "Turn left in 200 feet, onto X" — the actionable verb fires first (1-2 syl), distance second (3 syl), street-name last. If cancelled mid-utterance, the driver still heard "Turn left." This is a meaningful UX shift but arguably more accessible for eyes-free users. Note this diverges from Google Maps parity (see F4.7).

(b) **Add a "cancel guard"** in `nav-ui.js.onVoice`: if the current utterance is within 1.5 s of completion (track via `utterance.onend` or time-since-`speak()`), defer the new utterance via a short setTimeout rather than cancelling. Reroute announcements (highest-priority) bypass the guard. This is an nav-ui.js change, violating §2 NG5, and cross-cuts Issue 2 into a Phase 2 UX spec. Flag as a dependency; don't ship Issue 2 without it if (a) is not adopted.

Absolute minimum: §6.5 field gate should explicitly test the "reroute-while-chain-speaking" scenario with Cameron's Villa Rita detour route to catch this before merge.

---

### F4.4 — Short-turn information overload: mixed-spacing cluster produces a 65-syllable run in <15 seconds

**Severity:** SHOULD-FIX

**Claim:** Cameron's own concern: "I can see how it could be, but it's also the most generally useful approach." The spec doesn't commit to a view; R4's job is to. Trace the Villa Rita Seg 4 in §5.4:

> "In 200 feet, turn left onto North Black Canyon Highway, then in 400 feet, turn left onto West Wescott Drive"

~32 syllables = 6.4-8.6 s speech. At 25 mph, the 400 ft (122 m) between the two maneuvers = 10.9 s of travel. So the chain utterance ends ~2-4 s before the NEXT maneuver's own near-tier fires ("In 100 feet, turn left onto West Wescott Drive" — ~11 syllables = 2.2-3 s).

Total audible content in the 122 m between turns: ~43 syllables in ~11 s. That's **3.9 syl/s of sustained voice**, or about 2.3 words/s, continuously. For the driver already executing a left turn and monitoring for oncoming traffic on a wide 4-lane road, this is taxing.

And that's not the worst case. Villa Rita Seg 7 has two turns 35 m apart — §5.4 spec shows "In 100 feet, turn right, then in 100 feet, turn right." Near-tier fires at 35 m; with no chain suppression active for the second maneuver (I11 suppresses far, not near), the second near-tier fires at maneuver 2 at another 35 m. Two ~8-syllable utterances in ~6 seconds — fine standalone, but stacked behind the Seg-4 chain these combine into ~51 syllables of continuous speech over ~17 seconds.

**Impact:** This is the ship-gate regression criterion in §7.4 ("No new class of unexpected announcements. Total prompt count is 11"). Prompt *count* is the wrong metric when utterance length is doubling. The true metric is **speech-seconds-per-minute of drive.**

Rough estimate for Villa Rita → Costco drive (~6-7 minutes of nav):
- Current: 11 prompts × ~3.5 s avg = 38 s of speech across 6 min = 10.5% speech.
- Spec: 11 prompts × ~5.5 s avg = 60 s of speech across 6 min = 16.7% speech, with **bursts** of 60%+ during the 3-maneuver cluster.

**Recommendation:** Add to §7 a new ship-gate criterion: "total speech-seconds during the drive does not exceed 150% of current ship." Measure via either (a) instrumentation at `onVoiceCb` that logs utterance start + end timestamps (closure over `utterance.onstart`/`utterance.onend`), or (b) syllable-count modeling per utterance from the final text. Cameron runs it on the field drive; if the ratio exceeds 150%, iterate on prefix shortening (F4.2) or chain-suppression heuristics before re-shipping.

Separately: re-open the question of whether the chain-append should fire a distance prefix at all when the chain's `distBetween < 100 ft / 30 m`. Currently §5.2 has a global `DISTANCE_PREFIX_CUTOFF_METERS = 30` but my read is it applies to `distToNext` and `distBetween` uniformly — ensure test coverage for a chain-append at `distBetween = 25 m` (should be "then turn right", not "then in 80 feet, turn right").

---

### F4.5 — Lowercase "in" after "then" creates a homophone hazard for one class of voices ("than")

**Severity:** NICE-TO-HAVE

**Claim:** §5.2 chain-append: "Turn left onto 21st Avenue, then in 1/4 mile, turn left..." (§5.2 `lcPrefix = afterPrefix.charAt(0).toLowerCase() + afterPrefix.slice(1)`). English TTS engines synthesize "then in" as `/ðɛn ɪn/`, distinct from "than in" `/ðæn ɪn/`, but the distinction is small (front-vowel swap) and low-bitrate voices (e.g., eSpeak fallback when no web voice loaded) collapse these. On a phone speaker in a car, the difference is arguably imperceptible.

**Impact:** Low. "Turn left, than in 1/4 mile" isn't confusing — the comma cadence resolves it. But the casing flip is purely cosmetic (for reading flow, which doesn't apply to TTS); it saves no speech time and changes nothing semantic. The upper-case "In" would be pronounced identically by any real TTS engine (TTS engines don't case-fold for phonetics).

**Recommendation:** Revert §5.2 to keep "In" capitalized throughout. "Turn left onto 21st Avenue, then In 1/4 mile, turn left..." reads oddly in print but TTS pronounces it identically to the lowercased variant; the reviewer's eye can tell the two are identical under synthesis. Simpler code, one less edge case. Nit only — not ship-blocking.

---

### F4.6 — Distance prefix is not always eyes-free-useful at near-tier range; "200 feet, turn right" trains the driver to ignore the prefix

**Severity:** SHOULD-FIX

**Claim:** At the new 65 m near-tier floor, the driver is ~5.8 s from the intersection. Any distance below ~100 ft (~30 m) is functionally "now" — eyes-free drivers don't measure-and-execute at that scale, they just turn when they hear the instruction. 200 ft / 65 m is an awkward middle: too close for the number to be actionable (no driver is measuring 200 ft out the windshield while driving), too far to skip.

Google Maps' actual near-tier behavior at this range (see F4.7) is usually just "Turn right onto X now" or just "Turn right onto X" — no distance. The distance is reserved for the *far* alert ("In a quarter mile, turn right onto X").

**Impact:** Every near-tier utterance is ~0.8-1.1 s longer than it needs to be, compounding F4.1 and F4.2. The driver hears "In 200 feet" repeatedly across the drive and learns to tune it out; when the far-tier fires "In a quarter mile" — where distance IS actionable — the driver has been trained to ignore the leading prefix. Net: Issue 2 *reduces* eyes-free utility in exchange for dashboard-like pseudo-precision.

**Recommendation:** Asymmetric prefix policy:

- **Far-tier:** always prefix (this is the whole point of Issue 2 — resolves the "turn right" ambiguity at 486 m).
- **Near-tier:** NO prefix at distances < 200 ft; prefix only at 200-500 ft. That is, set a separate `NEAR_TIER_PREFIX_CUTOFF = 60 m` that's independent from `DISTANCE_PREFIX_CUTOFF_METERS = 30 m`.
- **Chain-append:** prefix only when `distBetween > 50 m`.

This delivers Issue 2's primary value (disambiguating far-tier turns), retains eyes-free clarity on near/imminent turns, and buys back ~0.8 s of post-speech buffer on the near-tier — closing F4.1's net-improvement shortfall without lifting the floor further.

---

### F4.7 — Google Maps parity claim is false; GM does not prefix near-tier turns at surface-street range

**Severity:** SHOULD-FIX

**Claim:** Spec §5.1 docstring says "matching Google Maps conventions." From my knowledge of Google Maps' Turn-by-Turn voice behavior on iOS/Android (based on typical user experience, not primary documentation):

- **Far alert (0.25 mi – 2 mi out):** "In a quarter mile, turn right onto X." ✓ Spec matches.
- **Near alert (~500-1000 ft out, depending on speed):** "Turn right onto X" — bare instruction, **no distance prefix.**
- **Execute alert (~100-200 ft out):** Often just the street name emphasized, or "Turn right onto X now" — **no distance.**

The spec's §5.4 has every near-tier utterance prefixed ("In 200 feet, ...") — this is NOT Google Maps behavior. Spec claims parity but delivers something more verbose.

**Impact:** If a beta tester switches from Google Maps and expects the same cadence, Geographica will feel chatty by comparison. If Cameron demos the fix to a friend who uses GM, the friend will say "why does yours keep saying the distance?" Parity claim undermines the professional-polish goal called out in CLAUDE.md.

Also: §9 "Issue 2" label in the commit message will use `feat(nav):` because it's "user-observable." OK — but the user-observable behavior it ships isn't what the spec says it is. Documentation debt, low severity but real.

**Recommendation:** Remove the "Google Maps parity" claim from §5.1. Replace with "matching Google Maps *far-tier* conventions" or "matching Google Maps conventions at ranges above the near-tier threshold." Pair with F4.6's asymmetric policy — under that revision the claim becomes more defensible ("matching Google Maps behavior across all three tiers" after the near-tier prefix is dropped below 60 m).

---

### F4.8 — BFCache `pageshow` handler may race restoreLastSidebarTab() with in-progress sidebar-tab click, causing visible flicker

**Severity:** NICE-TO-HAVE

**Claim:** Trace a plausible user sequence:
1. User is on Layers tab (default).
2. User taps Route tab — `initSidebarTabs` click handler fires, writes `sidebar-last-tab = route-panel` to localStorage at `app.js:1161`.
3. User locks phone mid-tap — the click's DOM class changes might or might not have completed depending on the OS interrupt timing (iOS backgrounds aggressively).
4. User returns 30 min later. BFCache restore fires `pageshow(persisted=true)`. New handler calls `restoreLastSidebarTab()`.
5. `restoreLastSidebarTab` reads localStorage → `route-panel`. Checks if Route tab already has `.active`. If step 3's class changes committed, it does → early-return, no-op. If not → `targetTab.click()` fires programmatic click, which replays the handler logic AND re-writes localStorage (harmless, same value).

Case 5b (BFCache snapshot captured class state post-DOM-commit, but our localStorage says the same tab should be active) is the normal path and is harmless.

Case 5c (BFCache snapshot captured pre-DOM-commit, so tab DOM looks like Layers but localStorage says Route): `targetTab.click()` correctly fires, restoring Route. But it goes through the FULL click handler including `initAdmin`-polling-start semantics (comment at `app.js:4115`). If `admin-panel` was the target, this starts admin polling. Benign, intentional per the comment.

**BUT** — consider this adversarial case: user is on Layers. They click Route. Between `localStorage.setItem` (line 1161) and the next paint, iOS backgrounds. They return; BFCache restores the page DOM state as it was *at backgrounding* (which may be mid-frame — Route tab button class has `.active`, Route panel has `.active`). The listener fires `restoreLastSidebarTab`, sees Route already active, early-returns. Result: no restore needed, no flicker. Good.

So the BFCache race is actually fine in practice. But the spec doesn't discuss this sequence — it assumes BFCache always restores the PRE-click state. On iOS Safari the behavior is complex and not fully documented.

**Impact:** Low risk of flicker; the idempotency guard at `app.js:4113` handles all the cases I can trace. But the spec's invariant G10 ("normal pageshow events are no-ops") is stronger than what's actually provable — a `pageshow` with `persisted=true` that arrives right after a DOMContentLoaded-triggered restore is NOT a no-op if the BFCache snapshot has stale tab state.

**Recommendation:** Tighten G10's language to "idempotent, not no-op." Add a comment inside the `pageshow` listener noting that the DOMContentLoaded path and pageshow path can both fire for a single page load in rare iOS cases (cold start that gets BFCache-backgrounded before first paint), and both calls converge on the same DOM state. No code change needed; documentation only.

Separately: verify on an iPhone that the first-time page load does NOT fire `pageshow(persisted=true)` — if it does (I don't believe it does, but iOS is quirky), the programmatic click on bootstrap will re-run admin polling init, which MAY double-subscribe. Trace this in §6.3 field test, not just the background-and-return case.

---

### F4.9 — Cross-voice variance is ignored by the §4.2 math; spec should model a floor-lift that works for the worst voice

**Severity:** SHOULD-FIX

**Claim:** §4.2 assumes "~3 s typical utterance." In practice:

- **Samantha / Siri fast:** ~5 syl/s, short prompts ~2.5 s, prefixed ~3.4 s.
- **Daniel / Alex / default iOS male:** ~3.7 syl/s, short prompts ~3.5 s, prefixed ~4.6 s.
- **eSpeak fallback (when no loaded voice, which voice-picker tries to avoid but can happen during startup):** ~4 syl/s but robotic cadence adds ~15% padding → prompts ~3.8 s, prefixed ~5.0 s.

The spec picked +1.3 s at 25 mph as the target buffer. With 3 s speech → post-speech = 5.8 − 3 = 2.8 s. With 4.6 s speech (slow voice + prefix) → post-speech = 5.8 − 4.6 = **1.2 s** — that's WORSE than the current 1.5 s baseline. Issue 1 regresses for users who selected a slow voice from the voice picker.

This is the same root cause as F4.1 but the framing is different: F4.1 says the floor is too low; F4.9 says the floor should be voice-duration-aware.

**Impact:** voice-picker was shipped Apr 21 explicitly to let users select slower/clearer voices (accessibility goal). Issue 1's floor lift undermines that: users who chose a slow voice (likely for accessibility reasons) are the ones MOST harmed by the floor being calibrated to a fast voice. Ethical regression in addition to the buffer-math regression.

**Recommendation:** Two options:

(a) Lift the floor to the slow-voice-worst-case value (F4.1's 75 m). Simple, costs no code complexity, costs a little extra early-prompt at the expense of users who chose fast voices — which is the LESS accessibility-sensitive cohort anyway.

(b) Make the floor voice-speed-adaptive: `floor = 65 + max(0, 4.5 - estimatedUtteranceSeconds) * speed`. Requires wiring an utterance-duration estimate from voice-picker into navigation.js. More precise but increases cross-file coupling (violates NG5's spirit).

Strong recommendation: **(a)**. It's one number change; it makes the product more forgiving for the worst case; it aligns with the accessibility goal voice-picker was built to serve.

---

### F4.10 — Issue 1 pedestrian floor asymmetry is defensible; no change needed, but flag the UX rationale in the spec text

**Severity:** NICE-TO-HAVE

**Claim:** Spec §4.1 / NG2: "Walking-pace scenarios have ample buffer today; a change here would expand scope without field evidence." I agree with the rationale. At 1.4 m/s with 15 m floor, time-to-intersection is 10.7 s — more than enough for any voice to complete.

Worth checking: does the spec need to confirm that pedestrian costing wouldn't benefit from *any* prefix change? Issue 2 applies prefix to all three costings (§1 item 2: "apply to all three costings"). So pedestrian will also get prefixed prompts ("In 50 meters, turn left..."). At 1.4 m/s, 50 m = 36 s of walking. A pedestrian hearing "in 50 meters, turn left" 36 s ahead of the turn is... weirdly early. Usual pedestrian nav cadence is 10-15 s of lead time.

**Impact:** Low. Pedestrians are a niche Geographica audience (surface-street mesh-network AREDN ops). But the prefix-everywhere rule delivers an unexpected pedestrian UX where the app "talks too far ahead."

**Recommendation:** Add a pedestrian-specific note to §5.4 (or better, §1): at walking pace, prefixes may feel premature; de-scope Issue 2's pedestrian application to only the *near* tier, OR limit pedestrian-tier prefixes to distances above 100 m (i.e., raise `DISTANCE_PREFIX_CUTOFF_METERS` for pedestrian costing). Alternatively, accept that pedestrians get more notice than is strictly necessary and let field testers complain before tuning.

Not a ship-blocker. Document the decision with a rationale paragraph so the next maintainer knows it was considered.

---

### F4.11 — Sidebar BFCache fix trace: user's LATEST choice IS respected; but add a regression guard test

**Severity:** NICE-TO-HAVE

**Claim:** The question posed in the attack-angle brief: "If the user deliberately switches to Layers tab, backgrounds the app, returns — will it restore them to Route (where they initiated nav) against their most recent choice?"

Trace the click handler at `app.js:1152-1163`:
1. User on Route panel (localStorage: `route-panel`).
2. User clicks Layers tab. Click handler runs, writes `sidebar-last-tab = layers-panel`.
3. User backgrounds app. BFCache captures state with Layers active.
4. User returns. `pageshow(persisted=true)` fires. `restoreLastSidebarTab` reads localStorage → `layers-panel`. Checks if Layers is active → YES (BFCache preserved it) → early-return.

**Result: user sees Layers, which matches their last-click choice. No regression.**

The only case that goes wrong is if localStorage and BFCache-DOM are out of sync (step 5c in F4.8), and in that case `targetTab.click()` restores from localStorage, which IS the user's last explicit click. So localStorage is authoritative, and that's correct.

**Impact:** None — spec is correct. But the trace is non-obvious enough that an adversarial review should verify it, and a test should assert it.

**Recommendation:** Add to §6.3 structural test (or better, a JS unit test if the bootstrap test runner supports DOM): simulate the sequence (user clicks Route, then Layers, then we simulate BFCache restore by manually manipulating `.active` classes and invoking the listener). Assert that `restoreLastSidebarTab` converges on the localStorage value regardless of DOM state. This is a logic-invariant test, not an integration test — cheap to write, guards against future regression of the precedence rule.

Additionally: consider a **max-age** check on the localStorage value. If `sidebar-last-tab` is >24 hours old, treat it as stale and revert to Layers default. Rationale: user who hasn't touched the app in a week probably doesn't remember they last had Route open. Out of scope for this spec but worth a future-work note in §7.

---

### F4.12 — Issue 2 §5.4 claim of "prompt count unchanged (11)" is testable but not tested on live Valhalla output

**Severity:** SHOULD-FIX

**Claim:** §5.4 table shows the Villa Rita → Costco fixture with 11 prompts. This is from the TTM v3 field drive. BUT: the §5.4 table is derived from a synthetic fixture matching Valhalla's output, not from re-running the actual route through current Valhalla. Valhalla updates (between initial fixture build and now) may have changed the `verbal_transition_alert_instruction` and `verbal_pre_transition_instruction` shapes. In particular:

- Does Valhalla ever emit `verbal_transition_alert_instruction` with the form "In about a quarter mile, Turn right onto X"? The "about" qualifier would break `BAKED_DISTANCE_RE` regex (it requires `[a-zA-Z0-9.\s]+?` greedy-match but the negative lookahead `(?=[A-Z])` after the unit may or may not permit "about" + "a").
- Test vector from §5.2: "In 1.5 miles, Merge onto I-5." The regex matches. But what about "In 1 and a half miles, Merge onto I-5."? The regex's `[a-zA-Z0-9.\s]+?` allows "1 and a half" but doesn't terminate cleanly on "miles" because `\s(?:feet|foot|mile|...)` requires a space before the unit. "1 and a half miles" should match. Probably fine.

This feeds G8 (§2) which the spec lists as an open question for adversarial review.

**Impact:** A partial-strip produces "In 200 feet, 1 and a half miles, Merge onto I-5." — ungrammatical and confusing. If Valhalla output has a single weird case the regex doesn't handle, Issue 2 gets a bad review in the first week.

**Recommendation:** Before merging Issue 2:

1. Run the current Valhalla output for 3-5 canonical routes (Villa Rita → Costco; a highway-heavy route; a 50-mile interstate leg) and capture the raw `verbal_transition_alert_instruction` and `verbal_pre_transition_instruction` strings. 100% of the strings should either match BAKED_DISTANCE_RE fully (strip succeeds, clean residual) or fail to match (no change).

2. Build a test fixture `valhallaActualOutput.json` with these raw strings and add a test that verifies `stripBakedDistance` produces valid-English output for every string in the fixture.

3. Document in §5.2 a fallback policy: if the regex fails to cleanly strip (residual still contains "mile" or "feet" in the first 15 characters), skip the prefix-prepend for that prompt. "In 200 feet, about a quarter mile, turn right" is worse than "About a quarter mile, turn right."

This addresses §9's open question G8 directly and makes §5.4's "prompt count: 11" claim verifiable, not declarative.

---

### F4.13 — Cumulative: the spec tries to do too much in one PR, blocking Issue 3 on Issue 2 risk

**Severity:** SHOULD-FIX (process)

**Claim:** §10 explicitly sequences Issue 1 + 2 + 3 in a single PR with "delivery cohesion" as rationale. But:

- Issue 3 (sidebar BFCache) is a 10-line fix, orthogonal to nav, field-verifiable in 30 seconds.
- Issue 2 (prefix + strip regex) is the most complex change and has the most adversarial surface (this review identifies 3 MUST/SHOULD issues in Issue 2 alone).
- Issue 1 (floor lift) is a 3-line constant change.

If Issue 2's field drive surfaces a regression (likely, per F4.1 / F4.2 / F4.3), the spec's §8 rollback story requires reverting Issue 2 out of a combined commit, which is messy. Meanwhile the user-facing value of Issue 3 (sidebar respecting persistence on iOS) is delayed behind Issue 2's review cycle.

**Impact:** Process risk, not correctness risk. But the "delivery cohesion" argument in §10 is weak — the three issues share a field-test gate (§7) but not a codebase surface (§3 is explicit that each issue is localized). Shipping them together conflates their risk profiles.

**Recommendation:** Split into two PRs:

- **PR 1:** Issue 3 (sidebar BFCache). 30-minute review, ships immediately, closes a user-visible iOS defect.
- **PR 2:** Issue 1 + Issue 2 (voice). Full adversarial review, combined because they touch the same file and invariants.

Each PR gets its own release-please entry; release-please can batch them into one version bump if they merge close together. The process cost of separating is near-zero; the rollback clarity is a big gain.

Alternatively: keep the single-PR structure BUT sequence commits as 1, 3, 2 (Issue 1 → Issue 3 → Issue 2), so if Issue 2 needs revert, it's the HEAD commit and revert is trivial.

---

## Count summary

- **MUST-FIX: 2** (F4.1 floor lift under-specified; F4.2 chain utterance exceeds time-to-intersection budget)
- **SHOULD-FIX: 6** (F4.3 cancel race on chain+reroute; F4.4 speech-seconds-per-minute overload; F4.6 near-tier prefix trains ignore-behavior; F4.7 Google Maps parity claim false; F4.9 slow-voice users regress; F4.12 Valhalla output not verified; F4.13 process split)
- **NICE-TO-HAVE: 3** (F4.5 "then in"/"than in" homophone; F4.8 pageshow-DOM-race documentation; F4.10 pedestrian prefix feels premature; F4.11 BFCache last-click test guard — correction: this is 4, making 3 NICE + 1 additional guard-test suggestion)
- **Rejected (no findings)**: 0

**Total: 11 findings across 11 sections.**

## Bottom-line product verdict

**The spec does not, as written, solve Cameron's symptom for all users.** Slow-voice users regress; chain-append users see utterances end *after* they cross the intersection. The root cause is a single assumption — "~3 s typical utterance" — that's too optimistic by 50% for the worst-case voice/prefix combination.

**The spec should not ship without:**
- F4.1 (larger floor lift, to 75 m auto / 45 m bicycle), OR F4.6 (asymmetric near-tier prefix policy that drops prefix below 60 m) — ideally both.
- F4.2 (shortened chain-append format, OR chain-append budget enforcement).
- F4.12 (validate regex against actual Valhalla output).

The Sidebar BFCache fix (Issue 3) is independently correct and should ship; F4.13 recommends separating it from the voice work to de-risk its rollout.

**Agent pinyon-sub-r4, round 4 product+UX review complete.**
