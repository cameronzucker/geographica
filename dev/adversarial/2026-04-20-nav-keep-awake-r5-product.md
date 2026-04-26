---
round: 5
angle: Product / user-model / scope
reviewer: general-purpose
date: 2026-04-20
---

# Round 5 — Product, user, scope

## Findings

### F5.1 — "Safety-of-life" framing is load-bearing but imprecise
**Severity:** SHOULD-FIX
**Framing question:** Does wake-lock actually prevent the harm the spec claims?
**Current spec position:** §1 calls silent nav suspension "a safety-of-life failure mode." The implied causal chain: screen dims → JS throttled → nav stops → driver endangered.
**Challenge:** The causal chain as written is wrong at the critical step. A driver whose phone has dimmed and gone quiet is not endangered by the *absence* of voice prompts — the road does not become more dangerous because the nav app is asleep. The driver is endangered by the *distraction* of looking down to check why the app went quiet (eyes off road for 2–4 s at 60 mph ≈ 175 ft of blind travel). Wake-lock genuinely mitigates *that* distraction. It does NOT mitigate the loss of nav itself, because a dark phone is functionally identical to no phone — the driver falls back on signs and memory. Framing the failure as "nav stopping is unsafe" overclaims; framing it as "driver checking a dark phone is unsafe" is defensible and should be how §1 reads. The difference matters because it disciplines the scope: we're fixing a *distraction* problem, which is why G4 (no UI chrome) is correct, and why NG3 (no alarms on backgrounding) is correct — both are anti-distraction choices.
**Recommended resolution:** Rewrite §1 summary to ground the safety claim in driver distraction, not nav continuity. One sentence change; sharpens the entire spec's internal logic.

### F5.2 — Persona is over-indexed to "driver in a car mount"
**Severity:** SHOULD-FIX
**Framing question:** Does the spec read the right user?
**Current spec position:** Spec speaks of "driver," "cab," "phone down without interacting" — a hands-off, vehicle-mounted persona.
**Challenge:** Geographica's stated primary use case (per CLAUDE.md and README) is AREDN mesh / field comms / offline-first GIS. A non-trivial fraction of real use is phone-on-a-table at a field camp, phone-in-hand while on foot, or tablet-on-a-pack-frame. For those personas: auto-dim is not a safety issue, it's a nuisance. Wake-lock is still desirable (you don't want to unlock your phone every 30 s to check progress) but the *framing* changes — it's an ergonomics feature, not a safety feature. The spec's "driver" language will read as off-key to a ham operator doing Search-and-Rescue coordination, who is the canonical AREDN user. Cameron-as-primary-user is the strongest persona match (he does drive with this) but beta testers will not all map to that. Two-paragraph fix: acknowledge the broader field-ops persona, keep the driver scenario as the *safety-critical* instance that motivates the rigor, but don't let driver language dominate.
**Recommended resolution:** Add one paragraph to §1 naming both personas (field operator + in-vehicle navigator); keep driver as the safety-critical case that sets the design bar.

### F5.3 — G4 "entirely silent to the driver" is plausibly over-corrected
**Severity:** NICE-TO-HAVE
**Framing question:** Is zero-UI the right answer, or a design purity pose?
**Current spec position:** §2 G4: "no visual indicator, no audible chime, no banner, no modal. The feature is self-evidencing (the screen staying on IS the evidence that it works)."
**Challenge:** The self-evidencing argument only holds when the feature *works*. In §5.3 (NoSleep not loaded), §5.4 (NoSleep enable throws), and §5.16 (Low Power Mode) the feature silently no-ops. The self-evidencing logic inverts: if the screen dims mid-nav, the driver correctly infers wake-lock failed — but by then they've already been surprised once, which is exactly the distraction F5.1 cares about. Google Maps and Waze both show a small always-on "navigating" chrome (route line, next-turn card) that doubles as wake-lock evidence without being hostile. The spec is not wrong to reject a dedicated "wake-lock is on" badge (that would be gold-plating), but it hasn't interrogated whether the *existing* nav UI already provides sufficient evidence. Probably yes — the nav banner at the top of the map is always visible during active nav. State that explicitly in G4 ("the existing nav banner is the evidence; no new indicator is needed") and G4 becomes defensible rather than feeling like over-reaction.
**Recommended resolution:** Tighten G4's justification — the argument isn't "no indicator," it's "no *additional* indicator beyond the nav banner that already serves this role."

### F5.4 — NG3 (no alarms on backgrounding) is correct for short hides, questionable for long hides
**Severity:** SHOULD-FIX
**Framing question:** Is "never alarm on background return" actually the right rule for ALL background durations?
**Current spec position:** §2 NG3: "Audible or visual alarms during driving are rejected as hostile."
**Challenge:** The reasoning is sound for the common case (home-button press for 3 s, notification peek for 5 s). It is less obviously sound for the pathological case: driver takes a 6-minute phone call while nav is active, during which three turns were missed. On return, the stale-GPS watchdog and off-route detector will fire their normal recovery — but from the driver's perspective, the phone is now giving them a *correct* announcement ("rerouting") that they would hear as a confusing surprise because they missed the *reason* it's rerouting. There's an argument for a single, brief, voice-only post-return announcement: "navigation resumed, rerouting" — same modality the driver is already using (audio), minimal additional cognitive load, and actually *less* hostile than a silent reroute that might be mistaken for a bug. This is not a shower-safety claim; it's a recoverability/comprehensibility claim. The spec conflates "don't alarm" (correct) with "don't announce" (potentially wrong). Worth an explicit carve-out: "brief voice confirmation on return from >60 s background is allowed and may be added in a follow-up spec."
**Recommended resolution:** Keep NG3 but narrow it: "no alarms; brief voice confirmation on return from long backgrounding is not in scope for this spec but is not prohibited by it." Defers the question without closing it.

### F5.5 — OS4 (voice TTS survival) is the actual safety feature; wake-lock is a prerequisite
**Severity:** MUST-FIX
**Framing question:** Is the spec naming the right hero?
**Current spec position:** §9 OS4: "Voice TTS survival under tab throttling. Known concern... Monitor as a regression after this ships; file follow-up if observed."
**Challenge:** This is buried too low. If the driver is relying on voice (which is the only safe modality while driving — visual glances at the phone are precisely what we're trying to eliminate), then audio continuity is the primary safety property, and wake-lock is one of two independent mechanisms needed to preserve it. The other mechanism is speechSynthesis behavior under tab visibility transitions, which is browser-specific and not addressed here. A spec that ships wake-lock and declares victory on the "silent nav" problem, while leaving TTS-under-throttle as a "monitor for regressions" footnote, is misrepresenting its own completeness. Either: (a) elevate TTS survival to a co-goal and plan to verify it in §6.3 manual acceptance, or (b) explicitly scope the spec as "wake-lock is necessary but not sufficient for reliable voice nav; Spec C will address TTS queueing." The current phrasing — OS4 as a casual footnote — lets a reader conclude the problem is solved when it's half-solved.
**Recommended resolution:** Move OS4 into §1 summary as an explicit boundary: "This spec addresses the screen-stays-on half of the silent-nav failure. Voice-under-throttle is a sibling concern addressed separately." Add to §6.3 a manual check: after returning from a 10 s tab-hide, does the next voice utterance fire? If not, file the sibling spec immediately.

### F5.6 — Silent degradation in Low Power Mode is an accepted-debt decision that needs explicit consent
**Severity:** SHOULD-FIX
**Framing question:** Is "user chose battery over features" the right mental model?
**Current spec position:** §5.16: "Documented degradation, not a bug to fix."
**Challenge:** The claim "user who enabled Low Power Mode prioritized battery" is plausible for a user who enabled LPM *today, deliberately*. It is wrong for iOS users whose phone auto-enters LPM at 20 %, which happens routinely on long drives exactly when nav matters most. A beta tester in LPM will experience silent wake-lock failure, no warning, and will correctly but uselessly conclude "the feature is broken." This is the single most likely path to a bad beta-tester bug report on this feature. Two options: (a) accept the debt explicitly, with a console.warn logged once per session (already specified in §5.4), AND add to user-facing docs that LPM disables keep-awake — "it just works now" is NOT sufficient discoverability here. (b) Detect LPM-plausible conditions (battery < 20 % and charging === false) and surface a *one-time* toast: "Screen keep-awake disabled due to Low Power Mode — tap for info." NG3 says no alarms during nav; a pre-nav-start advisory is different and is probably defensible. Option (a) is the right call for this spec, but the README/release notes must reflect it.
**Recommended resolution:** Add to §9/§10: "Release notes will state: 'On iOS, Low Power Mode disables the screen keep-awake feature. Disable Low Power Mode or keep the phone plugged in for uninterrupted navigation.'"

### F5.7 — Rollout story is absent
**Severity:** SHOULD-FIX
**Framing question:** How does a beta tester learn this feature exists and was fixed?
**Current spec position:** Spec does not address user-visible announcement.
**Challenge:** Beta testers have been encountering auto-dim behavior for weeks (implied by the brainstorm framing). When this ships, "it just works now" is sufficient for the *feature* but not for *bug reports already in flight*. If a tester filed "my phone dims during nav" last week, and this ships today, they need to know (a) their report is resolved, (b) what to do if they still see the problem (probably LPM per F5.6, or an HTTP-over-AREDN NoSleep autoplay block), and (c) that the absence of a UI indicator is intentional, not a half-finished feature. This belongs in CHANGELOG.md under the release that ships this, plus a one-paragraph entry in the release notes/README. The spec should name the deliverable.
**Recommended resolution:** Add to §10 acceptance criteria: "CHANGELOG entry written describing the fix and its known-limitation (LPM). Release notes updated."

### F5.8 — Spec is right-sized, not over-engineered
**Severity:** CORRECT
**Framing question:** Is 500+ lines of spec for a 2-file feature ceremony?
**Current spec position:** §4 provides canonical implementation code; §5 lists 17 failure modes; §6 specifies 6 Python + 12 JS tests.
**Challenge:** At first glance, yes — this looks like 10:1 spec-to-code ratio. But the failure modes in §5 are not padding; every one of them is a real race or degradation path (§5.7 acquire/release race is genuinely subtle, §5.16 LPM is genuinely user-impacting, §5.13 MutationObserver rejection is a real defense-in-depth point). The test list in §6 maps 1:1 to the failure modes, which is exactly how a well-scoped spec should look. The canonical `acquire()` code block in §4.3 is there because a subagent writing this without the race handling would ship a bug. For a feature sitting on a safety claim, this level of detail is appropriate and teaches transferable rigor — which matches the CLAUDE.md ethos of "process rigor > raw velocity, patterns that generalize to higher-stakes environments." A 50-line "ship it" spec would be under-spec'd for the safety claim; this is correct.
**Recommended resolution:** Keep as is. The spec length is load-bearing.

### F5.9 — Counterfactual: is the feature load-bearing?
**Severity:** CORRECT
**Framing question:** What happens if we DON'T ship this?
**Current spec position:** Implicit assumption that shipping is the right call.
**Challenge:** The counterfactual is "tell users to enable system-level Keep Screen On, or to increase screen timeout to Never during nav." On Android this is a developer-options toggle; on iOS this is Settings → Display → Auto-Lock → Never. Both are real user-accessible alternatives. The argument against them: (a) they apply system-wide, not just during nav — battery drain on a forgotten setting; (b) they require remembering to toggle before/after nav, which a driver about to leave will routinely forget; (c) they're multiple taps deep in OS settings, not discoverable from the app. The counterfactual harm is real: the user WILL forget to toggle, which means the first real drive ends in a dimmed phone. Wake-lock owned by the nav state machine is strictly better because the user never has to remember. The feature is load-bearing for the stated use case. Good.
**Recommended resolution:** Keep as is; the counterfactual is genuinely worse.

### F5.10 — G6 (survives tab-hide/tab-show) is correctly load-bearing
**Severity:** CORRECT
**Framing question:** Does the user benefit from silent re-acquisition?
**Current spec position:** §2 G6: "survives tab-hide / tab-show transitions... without the driver having to take any action."
**Challenge:** The attack was: if the driver isn't looking, they don't see the re-acquire; if they are looking, they see some UI flicker anyway, so G6 is engineering for a no-observable-effect scenario. Counter-counter: phone calls during driving are extremely common (the AREDN/SAR use case is literally "coordinator on a call while driving to the staging area"), and the behavior "call ends, return to nav, screen stays on without tap" is observably better than "call ends, return to nav, screen dims in 30 s because sentinel was released and nothing re-acquired it." The user benefit is not "smooth UI transition" — it's "the feature stays on across the most common interruption pattern." G6 is load-bearing; the attack was wrong.
**Recommended resolution:** Keep as is.

## Summary of actionable changes

Two MUST-FIXes (F5.5 elevating TTS boundary, F5.1 fixing the safety framing language) and four SHOULD-FIXes (F5.2 persona, F5.4 narrowing NG3, F5.6 LPM explicit consent, F5.7 rollout story) would tighten the spec meaningfully without adding implementation scope. The feature itself is correctly scoped, correctly placed at the right layer, and correctly rejects the gold-plating traps (dedicated badge, battery gating, MutationObserver hooks). Ship direction is right; the framing around what-safety-claim-we're-making and what-remains-unsolved needs sharpening.
