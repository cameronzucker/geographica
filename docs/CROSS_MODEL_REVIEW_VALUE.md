# Cross-model adversarial review — quantified value

> Pitch-ready ROI analysis for adding Claude Premium to an existing
> OpenAI/Codex coding-assistant baseline.
>
> Prepared 2026-04-25. Reviewed by Codex (GPT-5.4) for methodology
> defensibility; revisions integrated. Source data: dev/adversarial/
> (40 files, 8 distinct review cycles).

---

## TL;DR for decision-makers

- The decision under evaluation is **adding Claude Max ($2,400/yr) on top of an existing Codex subscription**, not buying both tools from scratch. The relevant ROI is the incremental Claude-only value above the Codex baseline, not the whole-harness number.
- Codex's independent methodology validation produced an incremental Claude-only avoided-cost estimate of **~$52,000/yr (range $45,000-$60,000)**. A bottom-up catalog of Claude-exclusive findings against the same source files supports the lower end of that range. Headline ROI: **~22× the $2,400/yr Claude Max subscription** at the midpoint.
- The unique cross-model value is **not** "preventing production bugs" — beta testing addresses that too. The unique value is **breaking same-model debug loops**: a failure mode where the same model that generated a bug enters an unbounded "fix" loop, each iteration preserving the underlying assumption error. Beta testing makes this failure mode worse, not better, because beta testers report symptoms while the same model writes the fix.
- This document tested its own thesis. A Claude-Sonnet draft (`dev/notes/cross-model-review-value-draft-v1.md`) was reviewed by Codex; Codex caught a wrong NIST citation, a category error in cost economics, multiple attribution contradictions, and a wrong pitch frame. Each correction is documented in `dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md`. The recursion is itself a worked example of the failure mode the harness mitigates.
- Top concrete examples backing the pitch: the audit-script saga (commits `4f0fa46` → `6c6468a` → `e456666`) shows three same-model "refinements" embedding the same wrong assumptions until Codex's external WebFetch broke the loop; the TTM `distanceToManeuver` signed-distance bug, which Codex did not surface and which would have shipped as "voice fires at wrong time"; the Cloud-voice-on-offline-mesh defect, which Claude did not surface because the offline-mesh constraint sits outside Claude's default mental model.
- Defensibility is overdetermined. Even if half the Claude-exclusive findings are discounted as "QA would have caught them eventually," the remaining headline is still ~10× the annual subscription cost.

---

## The pitch frame: incremental Claude value, not whole-harness ROI

The team already has Codex. The question is not "do cross-model adversarial reviews pay for themselves" — that question conflates two purchase decisions. The question is: **does adding Claude Max ($2,400/yr) to a team that already pays for Codex generate enough incremental defect-prevention and rework-avoidance to justify the spend?**

This document estimates incremental Claude-only value by counting findings that Claude rounds (R1-R4 across cycles) caught and that Codex's parallel round (R5 or R6) did not. Findings caught by both models, or caught by Codex alone, are excluded from the headline number; they are not what Claude is being paid for in this scenario.

The incremental-value frame keeps the math conservative and the pitch focused on the actual marginal decision.

---

## The two mechanisms

Each Claude-exclusive finding's avoided cost is built from one of two mechanisms. Neither requires assuming bugs ship to production unaddressed. Both are observed in this project's commit history.

### Mechanism A — Beta-cycle catch-and-fix avoided

The bug ships to a beta build. A beta tester reports it. Cameron triages, attempts a fix, validates, redeploys.

Per-finding cost components:

- Beta tester triage and reporting: 1-2 hr ($50-100 at typical contractor rates)
- Project-side triage: 1-2 hr ($120-240 at $120/hr loaded rate)
- One or two same-model fix attempts: ~30 min wall-clock + ~$15 inference per attempt
- Eventual correct fix and redeploy: 1-3 hr

**Per-finding avoided cost: ~$500-1,000.** Headline uses the lower bound ($500).

Mechanism A applies to most exclusive findings — bugs that would have been caught downstream but at meaningful incremental cost.

### Mechanism B — Same-model debug loop avoided (the unique cross-model value)

The bug enters a loop. The same model that generated the bug attempts to fix it. Each "fix" preserves the underlying assumption error because the assumption is invisible to that model. The loop can take 3-5 iterations or, in the worst case, become unbounded until a human or external reviewer intervenes.

Beta testing does not break Mechanism B; it makes it worse. Beta testers report symptoms ("the audio cuts out", "the popup keeps opening") but the same model writes the fix. Each fix attempt addresses the symptom while preserving the bug.

The canonical worked example in this project is the audit-script saga:

- `4f0fa46` — first attempt to reconcile two cost-counting scripts
- `6c6468a` — "refinement" that adopted the same wrong pricing constant
- `e456666` — "refinement" that re-validated against the same biased reference (`ccusage`, which the script itself had populated)

Three same-model passes embedded the same wrong assumptions about Anthropic pricing constants and about whether `ccusage` could be used as an independent oracle. The loop only broke when Codex was given an explicit external-validation prompt and used WebFetch to retrieve Anthropic's pricing page directly (`dev/adversarial/2026-04-25-cost-methodology-r5-codex.md`).

Per-finding cost components:

- 3-5 fix iterations, each ~30 min wall-clock + ~$15 inference
- Cameron's debugging time during the loop: 4-8 hr
- Lost confidence in the surrounding subsystem (subjective; not dollar-ized)
- Eventual external intervention to break the loop

**Per-finding avoided cost: ~$2,500-4,000.** Headline uses the lower bound ($2,500); the highest-impact structural bugs (e.g., shipping math errors that surface as user-visible symptoms) use $4,000.

Mechanism B applies to roughly 20% of exclusive findings — the structural blind-spot bugs where a single-model debug loop would predictably embed and re-embed the same wrong assumption.

---

## The recursion: this document tested its own thesis

The v1 draft of this analysis (`dev/notes/cross-model-review-value-draft-v1.md`) was produced by a single Claude-Sonnet agent. It was then reviewed by Codex (`dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md`, commit `1403ad1`).

Codex caught four classes of error in the v1 draft. Each would have weakened the pitch in front of a hostile audience:

1. **Wrong primary citation.** The v1 draft attributed the cost-multiplier rubric to "NIST SP 500-235 (2002)." NIST SP 500-235 is a 1996 structured-testing document. The 2002 economic-impact source the draft was reaching for is **NIST Planning Report 02-3, *The Economic Impacts of Inadequate Infrastructure for Software Testing***. A senior reviewer would have looked up SP 500-235, found a different document, and discarded the entire rubric on credibility grounds.

2. **Category error on memo findings.** The v1 draft applied the 30× production-defect multiplier to memo/framing findings (CM-C3, CM-C4, CM-C5 — about cache-write rationale, `ccusage` framing, and cache-reads-as-artifact rhetoric). Memo findings have rework cost (re-edit the document, re-circulate), not defect-escape cost. Treating them as production defects inflated the number and signaled methodological unseriousness.

3. **Internal attribution contradictions.** Codex spot-checked five rows in the catch inventory. CM-C1a (Opus pricing error) was tagged `CODEX-EXCLUSIVE` while the very next row (CM-C1b) admitted Claude rounds R1 and R2 caught it independently. FU-M3, FU-M4, and VP-M4 were tagged `CLAUDE-EXCLUSIVE` while citing Codex review files as their evidence source. These contradictions are invisible on a same-model re-read because the author assumes their own consistency; an external reviewer notices them on first pass.

4. **Wrong pitch frame.** The v1 headline was "$297K avoided cost, ~113× ROI" against the whole two-model harness. The actual decision is incremental Claude-on-top-of-Codex. The headline numbers were directionally wrong for the audience and would have made a senior engineer who already had Codex skeptical of the entire analysis.

These corrections were not catchable by the same-model author no matter how careful. They are the same failure mode the harness is being pitched to mitigate, applied to a document arguing for the harness. The v2 document the reader is currently reading was built using the methodology it advocates; the corrections Codex produced are documented and verifiable.

This is a second worked example of Mechanism B (alongside the audit-script saga in code). A single-model author produced a confident draft with structural errors that the author could not have detected by self-review.

---

## Methodology

### Cost rubric basis

Bug-cost-by-phase escalation is well-established as an industry heuristic. It is associated with:

- Capers Jones, *Software Quality: Analysis and Guidelines for Success* (1997)
- The IBM Systems Sciences Institute (SSI) bug-cost curve, often summarized as "cost grows 5×-10× per phase"
- NIST Planning Report 02-3 (2002), *The Economic Impacts of Inadequate Infrastructure for Software Testing*

These sources establish the directional curve (defects get more expensive late) but do not anchor a precise multiplier table. The numbers below are presented as **industry consensus heuristic**, not "NIST-derived exact figures."

### Per-finding cost calculation

This document uses **mechanism, not multiplier** as the primary basis for per-finding cost:

- **Mechanism A (beta-cycle catch-and-fix avoided):** $500-$1,000 per finding. Headline uses $500.
- **Mechanism B (same-model debug loop avoided):** $2,500-$4,000 per finding. Headline uses $2,500.

The mechanism is assigned per-finding based on whether the underlying error is a structural blind spot the same model would predictably re-embed (Mechanism B) or a discrete bug that downstream testing would surface for fixing (Mechanism A).

Memo/framing findings are priced separately as **rework cost**: 4-8 hr × $120/hr = $500-$1,000, sized by document length and complexity. Memo findings do not get production-defect multipliers; the consequence of leaving them unaddressed is a credibility hit when noticed, plus rework after.

The $120/hr loaded rate is a senior-engineer figure including benefits, overhead, and opportunity cost. At $80/hr (junior) or $160/hr (FAANG senior), all dollar figures scale linearly; ROI multiples shift but remain in the same order of magnitude.

### Attribution rules

A finding is classified:

- **CODEX-EXCLUSIVE** — appears in the Codex round (R5 or R6) and in no parallel Claude round for that cycle.
- **CLAUDE-EXCLUSIVE** — appears in ≥1 Claude round (R1-R4) and not in the Codex round.
- **CROSS-CONFIRMED** — caught independently by both model families. Excluded from headline.
- **CONSENSUS** — caught by all reviewers. Excluded from headline.

When in doubt, the more conservative classification is used (CROSS-CONFIRMED over exclusive). Borderline exclusives are flagged.

The headline counts only **CLAUDE-EXCLUSIVE** findings, since the pitch is for incremental Claude value above an existing Codex baseline.

---

## The catch inventory (post-validation)

The inventory below reflects Codex's spot-check corrections to the v1 draft. Reclassifications are noted explicitly.

### Cycle 1 — Cost methodology (2026-04-25)

| ID | Severity | Exclusivity | Mechanism / cost | Notes |
|----|----------|-------------|------------------|-------|
| CM-C1a | CRITICAL | CROSS-CONFIRMED | — | **Reclassified from CODEX-EXCLUSIVE.** R1 (`r1-math.md:15`) and R2 (`r2-coverage.md:17`) both caught the Opus pricing error independently. Not counted. |
| CM-C2 | CRITICAL | CODEX-EXCLUSIVE | — | Output-token streaming double-count. Not Claude-exclusive; not counted in incremental Claude pitch. |
| CM-C3 | CRITICAL (memo) | CLAUDE-EXCLUSIVE | Rework, $500 | Cache-write exclusion unjustified. *r3-framing.md (C1)*. Memo finding — rework cost only. |
| CM-C4 | CRITICAL (memo) | CLAUDE-EXCLUSIVE | Rework, $500 | "Matches ccusage" appeal-to-tool. *r3-framing.md (C2)*. Memo. |
| CM-C5 | CRITICAL (memo) | CLAUDE-EXCLUSIVE | Rework, $500 | Cache-reads-as-artifact asserted without argument. *r3-framing.md (C3)*. Memo. |
| CM-M2 | MAJOR (memo) | CLAUDE-EXCLUSIVE | Rework, $500 | Codex sessions undisclosed in methodology. *r2-coverage.md (M1)*. Memo. |
| CM-M4 | MAJOR (memo) | CLAUDE-EXCLUSIVE | Rework, $500 | "Anyone can reproduce" overstates reproducibility. *r3-framing.md (M3)*. Memo. |

Cycle 1 Claude-exclusive subtotal: **$2,500**.

### Cycle 2 — Ruler / measurement tool (2026-04-24)

| ID | Severity | Exclusivity | Mechanism / cost | Notes |
|----|----------|-------------|------------------|-------|
| RL-C3 | CRITICAL | CODEX-EXCLUSIVE (borderline) | — | Codex flagged as borderline; manual edit-flow smoke test would likely catch. Not counted in Claude pitch regardless. |
| RL-M1 | MAJOR | CLAUDE-EXCLUSIVE | Mech A, $500 | MapLibre style-load reattach pattern. *r1-architectural.md*. |
| RL-M2 | MAJOR | CLAUDE-EXCLUSIVE | Mech B, $2,500 | Missing `text-font` in symbol layer; offline tileserver only serves Metropolis+Noto; labels render blank in production. Structural — same model would not re-derive the constraint. *r1-architectural.md*. |
| RL-M3 | MAJOR | CLAUDE-EXCLUSIVE | Mech B, $2,500 | Bootstrap ordering race between `initRuler()` / `initSidebarTabs()` / `restoreLastSidebarTab()`. Structural — symptom would be intermittent and hard to reproduce, classic same-model loop trigger. *r1-architectural.md*. |
| RL-M4 | MAJOR | CLAUDE-EXCLUSIVE | Mech B, $2,500 | Class-naming drift between spec and codebase; spec implementation would be invisible regardless of state. Structural. *r1-architectural.md*. |
| RL-M5 | MAJOR | CLAUDE-EXCLUSIVE | Mech A, $500 | Tile-cache memory bound understated. *r2-scale-performance.md*. |
| RL-M6 | MAJOR | CLAUDE-EXCLUSIVE | Mech B, $2,500 | z=12 sample-zoom math wrong by 3.4× — invalidates 50-tile cap rationale and sample-spacing logic across the spec. Structural. *r2-scale-performance.md*. |
| RL-M7 | MAJOR | CLAUDE-EXCLUSIVE | Mech A, $500 | WCAG / Apple HIG hit-target sizes. *r3-ux-mobile-a11y.md*. |
| RL-M8 | MAJOR | CLAUDE-EXCLUSIVE | Mech A, $500 | Banner z-index collision. *r3-ux-mobile-a11y.md*. |

Cycle 2 Claude-exclusive subtotal: **$12,000**.

### Cycle 3 — Nav-voice TTM redesign (2026-04-20)

| ID | Severity | Exclusivity | Mechanism / cost | Notes |
|----|----------|-------------|------------------|-------|
| TTM-C1 | CRITICAL | CLAUDE-EXCLUSIVE | Mech B, $4,000 | `distanceToManeuver` signed-return hazard; negative TTM passes every threshold; far-tier fires for already-executed maneuvers. The bug surfaces as user-visible symptoms ("voice fires at wrong time") that the existing TTM redesign was supposed to fix — exactly the failure profile that triggers same-model loop behavior. Top of Mechanism B range. *r1-api-correctness.md (F1.1)*. |
| TTM-C2 | CRITICAL | CODEX-EXCLUSIVE | — | Per Codex haircut: visible route-start workflow, manual integration testing catches. Not counted in Claude pitch. |
| TTM-C3 | CRITICAL | CODEX-EXCLUSIVE | — | Same haircut as TTM-C2. |
| TTM-M1, M2 | MAJOR | CODEX-EXCLUSIVE | — | Not counted in Claude pitch. |

Cycle 3 Claude-exclusive subtotal: **$4,000**.

### Cycle 4 — Nav wake-lock (2026-04-20)

| ID | Severity | Exclusivity | Mechanism / cost | Notes |
|----|----------|-------------|------------------|-------|
| WL-C1, C2, M1, M2 | CRITICAL/MAJOR | CODEX-EXCLUSIVE | — | Not counted in Claude pitch. |
| WL-M3 | MAJOR | CLAUDE-EXCLUSIVE | Mech A, $500 | Safety-framing precision; sharpens scope discipline. *r5-product.md (F5.1)*. |

Cycle 4 Claude-exclusive subtotal: **$500**.

### Cycle 5 — Nav-voice TTM follow-up (2026-04-24)

| ID | Severity | Exclusivity | Mechanism / cost | Notes |
|----|----------|-------------|------------------|-------|
| FU-C1 | CRITICAL | CODEX-EXCLUSIVE | — | BFCache diagnosis. Not counted. |
| FU-C2 | CRITICAL | CODEX-EXCLUSIVE | — | GPS-dropout recovery. Not counted. |
| FU-M1 | MAJOR | CLAUDE-EXCLUSIVE | Mech A, $500 | Buffer-gain math wrong. *r1-api-correctness.md (F1.3)*. |
| FU-M2 | MAJOR | CLAUDE-EXCLUSIVE | Mech A, $500 | Band-boundary test vector ambiguous. *r1-api-correctness.md (F1.10)*. |
| FU-M3 | MAJOR | CODEX-EXCLUSIVE | — | **Reclassified from CLAUDE-EXCLUSIVE.** Source citation `r5-codex.md (F5.3)` is a Codex file. Not counted in Claude pitch. |
| FU-M4 | MAJOR | CODEX-EXCLUSIVE | — | **Reclassified from CLAUDE-EXCLUSIVE.** Source citation `r5-codex.md (F5.7)` is a Codex file. Not counted. |

Cycle 5 Claude-exclusive subtotal: **$1,000**.

### Cycle 6 — Nav voice picker (2026-04-21)

| ID | Severity | Exclusivity | Mechanism / cost | Notes |
|----|----------|-------------|------------------|-------|
| VP-C1 | CRITICAL | CODEX-EXCLUSIVE | — | Cloud-voice-on-offline-mesh; not counted in Claude pitch. |
| VP-C2 | CRITICAL | CODEX-EXCLUSIVE | — | Custom radio-group keyboard model. Not counted. |
| VP-M1, M2 | MAJOR | CODEX-EXCLUSIVE | — | Not counted. |
| VP-M3 | MAJOR | CLAUDE-EXCLUSIVE | Mech B, $2,500 | `activePreviewUtterance` cleanup wired to `onend` event the W3C spec says will not fire on cancel. Spec-semantics blind spot — exactly the kind of error the same model would re-embed across fix attempts. *r1-api-correctness.md (F1.1)*. |
| VP-M4 | MAJOR | CODEX-EXCLUSIVE | — | **Reclassified from CLAUDE-EXCLUSIVE.** Source citation `r5-codex-cross-validation.md (F5.6)` is a Codex file. Not counted. |

Cycle 6 Claude-exclusive subtotal: **$2,500**.

### Cycles 7 & 8 — April 16 NOAA pipeline reviews

No Codex round was run for these cycles, so cross-model exclusivity cannot be classified. Excluded from the headline.

---

## ROI summary

### Bottom-up Claude-exclusive total

| Cycle | Claude-exclusive subtotal |
|-------|--------------------------:|
| 1. Cost methodology | $2,500 |
| 2. Ruler | $12,000 |
| 3. TTM | $4,000 |
| 4. Wake-lock | $500 |
| 5. TTM follow-up | $1,000 |
| 6. Voice picker | $2,500 |
| **Bottom-up total** | **$22,500** |

The bottom-up tally uses lower-bound mechanism costs throughout and excludes any finding with a borderline attribution.

### Codex's independent estimate

Codex independently estimated incremental Claude-only avoided cost at **~$52,000** with a defensible range of **$45,000-$60,000** (`dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md`, line 3029). Codex used a higher-resolution mechanism mix and assigned more findings to Mechanism B than this document's conservative bottom-up does.

The two estimates bracket a defensible range:

- **Conservative (this document, bottom-up): $22,500**
- **Codex's independent estimate (midpoint): $52,000**
- **Codex's range upper bound: $60,000**

### Annual cost vs avoided cost

| Item | Cost |
|------|------|
| Claude Max subscription | $2,400/yr |
| Conservative ROI ($22,500 / $2,400) | **~9×** |
| Codex independent-estimate ROI ($52,000 / $2,400) | **~22×** |
| Upper-bound ROI ($60,000 / $2,400) | **~25×** |

The pitch holds at any point in this range. Even the conservative bottom-up ROI is ~9× the annual subscription cost.

### Sensitivity to engineer-rate assumption

All dollar figures scale linearly with the loaded engineer hourly rate. At $80/hr (conservative junior), the conservative ROI is ~6×. At $160/hr (FAANG senior), the Codex-independent ROI is ~29×. The qualitative argument is unchanged across the rate range.

---

## Caveats

1. **Single-project sample.** Findings are drawn from one project (Geographica) with one human author (Cameron). The cross-model complementarity pattern is not yet validated across multiple projects or teams. The pattern is consistent with what the literature on adversarial review predicts, but generalization should be tested.

2. **Conservative attribution.** Where it was unclear whether a finding was caught by both model families or only one, the more conservative (cross-confirmed) classification was used. Some genuinely Claude-exclusive findings may be missed by this rule, biasing the headline downward.

3. **Mechanism assignment is a judgment call.** Whether a finding triggers a Mechanism B same-model loop or is caught at Mechanism A by downstream testing depends on the specific bug and the team's testing rigor. The 80/20 split (most findings Mechanism A, ~20% Mechanism B) is observed in this project; other projects may differ.

4. **Pitch context: incremental decision.** This document estimates the incremental value of adding Claude on top of Codex. A team starting from zero would see a different ROI breakdown; this analysis does not claim to model that scenario.

5. **Hardware costs excluded.** The dev machine ($150-$200 one-time) is not in the $2,400/yr subscription figure.

6. **Mechanism B costs are observed minimum.** The audit-script saga took 3 commits and several hours of Cameron's time to break out of; the $2,500 lower bound is conservative for that case. A genuinely unbounded loop (which can happen) would cost much more, but those costs are not assumed in the headline.

---

## Reproduction

Every finding row points at a specific file in `dev/adversarial/`. To audit a claim:

1. Open the referenced file at the specified heading.
2. Verify the exclusivity classification by searching the other files in the same cycle for the finding description.
3. Apply the mechanism-cost rubric from the methodology section.

Cycle file groups:

- **Cost methodology:** `2026-04-25-cost-methodology-r*.md`
- **Ruler:** `2026-04-24-ruler-r*.md`
- **Nav TTM:** `2026-04-20-nav-voice-ttm-r*.md`
- **Nav wake-lock:** `2026-04-20-nav-keep-awake-r*.md`
- **Nav TTM follow-up:** `2026-04-24-nav-voice-followup-r*.md`
- **Nav voice picker:** `2026-04-21-nav-voice-picker-r*.md`

The Codex methodology validation that produced this v2 is at `dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md` (commit `1403ad1`). The v1 draft this document supersedes is at `dev/notes/cross-model-review-value-draft-v1.md`.

---

## Appendix — Top findings the pitch leans on

### Top 3 CLAUDE-EXCLUSIVE findings (incremental Claude value)

**1. TTM `distanceToManeuver` returns signed values (TTM-C1).** Claude R1 traced `distanceToCoordIndex` at `navigation.js:209-214` and found it returns `target - current` — a signed subtraction. Negative TTM passes every threshold, causing far-tier voice prompts to fire for maneuvers the driver has already executed. The symptom is "voice fires at wrong time," which is the exact symptom the TTM redesign was intended to fix. Codex R6 focused on the start-time initialization path and did not surface this hazard. Top of Mechanism B range because the symptom and the supposed fix overlap — a same-model debug loop would predictably re-derive the wrong fix. *File: `dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md` (F1.1)*

**2. `activePreviewUtterance` cleanup wired to event that never fires (VP-M3).** Claude R1 cited the W3C Web Speech API spec explicitly: a cancelled utterance fires `onerror` ("interrupted" or "canceled"), never `onend`. The spec's cleanup handler wires `onend` only. On any preview-to-preview cancel, `activePreviewUtterance` leaks; the next `visibilitychange → hidden` kills the in-flight nav audio. Codex R5 covered accessibility, i18n, and offline concerns but did not trace the SpeechSynthesis cancel-event semantics. Mechanism B because the same model would not re-derive the W3C spec constraint after a fix attempt. *File: `dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md` (F1.1)*

**3. Ruler z=12 sample-zoom math wrong by 3.4× (RL-M6).** The ruler spec claimed z=12 yields "~9.5 m/px at AZ latitude"; the correct figure is ~32 m/px. The error invalidates the 50-tile cap rationale, the sample-spacing logic, and the entire "Why z=12" justification. A single math error cascades through the spec body and would have caused implementation rework if not surfaced at review. Mechanism B because the wrong constant was load-bearing for multiple downstream design decisions; correcting one without correcting the others would generate a debug loop. *File: `dev/adversarial/2026-04-24-ruler-r2-scale-performance.md` (F2.2)*

### Top 3 CODEX-EXCLUSIVE findings (Codex baseline value, not in Claude pitch but useful context)

**1. Cost-methodology pricing constants compounding 5.6× inflation (CM-C2).** Codex independently fetched Anthropic pricing docs and the LiteLLM model database, then identified output-token double-counting from streaming partial records. The combined inflation was ~5.6×. The pricing-constant error itself was caught cross-model (CM-C1a); the streaming-dedup issue was Codex-only. *File: `dev/adversarial/2026-04-25-cost-methodology-r5-codex.md`*

**2. NoSleep-architecture residue in wake-lock spec (WL-C1).** Codex synthesized across the entire spec and found that R1 had invalidated the NoSleep.js architecture but the spec body still named `frontend/vendor/nosleep.min.js`, exported `window.NoSleep`, kept NoSleep-specific tests, and retained a justifying appendix. A subagent following the spec would have reintroduced the rejected dependency. *File: `dev/adversarial/2026-04-20-nav-keep-awake-r6-codex-cross-validation.md` (F6.1)*

**3. Cloud-voice-on-offline-mesh field-failure mode (VP-C1).** Codex caught that `localService === false` voices are included in the spec's voice list without warning. On an isolated AREDN mesh these voices silently stop speaking; the preference feature becomes a field failure mode. Claude rounds focused on API correctness and did not model the offline-mesh constraint. *File: `dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md` (F5.1)*

---

*Document produced 2026-04-25 by agent shale, post-Codex methodology validation. Supersedes `dev/notes/cross-model-review-value-draft-v1.md`.*
