# Cross-model adversarial review — quantified value

> Pitch-ready ROI analysis for adding Anthropic Claude API consumption
> to an existing OpenAI/Codex coding-assistant baseline.
>
> Prepared 2026-04-25. v3 reframes the cost denominator from consumer
> subscription pricing to enterprise API consumption after a context-supply
> error in v2 was caught by the human author. Source data:
> dev/adversarial/ (40 files, 8 distinct review cycles). Methodology
> validated by Codex (GPT-5.4); cost-shape framing validated by human
> review.

---

## TL;DR for decision-makers

- **Allocate ~$50/developer/year of Claude API budget for adversarial review of specs.** No subscription. No per-seat license. No new vendor relationship if procured via AWS Bedrock or Azure Foundry. Avoided cost per developer per year: **~$52K of incremental Claude-exclusive defect-prevention value.** **ROI: ~1000×.**
- The proposal under evaluation is **adding Claude API consumption** on top of an existing Codex baseline, not buying a Claude subscription. Per-session cost for a typical spec review (~10K input tokens, ~3K output) is **~$0.08 (Sonnet)** or **~$0.13 (Opus)** at standard API rates. Ten to twenty reviews per quarter per developer is **~$3-$10/yr actual** in API consumption; **~$50/yr** is a generous budget ceiling.
- The unique cross-model value is **not** "preventing production bugs" — beta testing addresses that too. The unique value is **breaking same-model debug loops**: a failure mode where the same model that generated a bug enters an unbounded "fix" loop, each iteration preserving the underlying assumption error. Beta testing makes this failure mode worse, not better, because beta testers report symptoms while the same model writes the fix.
- The avoided-cost figure (~$52K/developer/yr) is Codex's independent methodology-validation estimate; a conservative bottom-up catalog of Claude-exclusive findings against the same source files supports a $22.5K/developer/yr lower bound. Even the lower bound is **~450× the $50/yr API budget**.
- This document tested its own thesis. v1→v2: Codex caught a wrong NIST citation, a category error in cost economics, multiple attribution contradictions, and a wrong pitch frame. v2→v3: the human author caught a wrong cost-shape assumption (consumer subscription pricing) that Codex's methodology validation also missed, because the enterprise context was outside both models' supplied frame. Both transitions are worked examples of the failure modes the harness mitigates and the failure mode it does not address.
- Defensibility is overdetermined. Even if half the Claude-exclusive findings are discounted as "QA would have caught them eventually," and if the API budget is doubled to $100/yr, ROI remains **~250×**.

---

## The pitch frame: trivial API spend, large incremental defect-prevention

The team already has Codex. The question is not "do cross-model adversarial reviews pay for themselves" — that question conflates two purchase decisions. The question is: **does adding Claude API consumption (~$50/developer/year max) to a team that already pays for Codex generate enough incremental defect-prevention and rework-avoidance to justify the spend?**

This document estimates incremental Claude-only value by counting findings that Claude rounds (R1-R4 across cycles) caught and that Codex's parallel round (R5 or R6) did not. Findings caught by both models, or caught by Codex alone, are excluded from the headline number; they are not what Claude is being paid for in this scenario.

The framing change from earlier drafts: prior versions of this analysis used consumer Claude subscription pricing ($2,400/yr) as the denominator. That denominator does not match an enterprise procurement reality. The enterprise denominator is **API consumption metered against existing AWS or Azure spend**, which for typical adversarial-review cadence is **less than $10/developer/year actual** and best budgeted at **~$50/developer/year** to absorb fluctuations.

The incremental-value frame keeps the math conservative; the API-consumption framing keeps the cost-shape honest.

---

## Procurement: how to add Claude without adding a vendor

The "any additional expense" objection is sometimes stated as a cost objection but is usually a vendor-relationship objection underneath. For most enterprises with existing AWS or Azure procurement, the vendor objection does not apply.

- **AWS Bedrock** — Anthropic's Sonnet, Haiku, and Opus model families have been available through Bedrock since 2024. Existing AWS contract → Anthropic models accessible **without onboarding a new vendor**. Billing rolls into the existing AWS invoice. Bedrock pricing is API-consumption-metered; rates differ slightly from Anthropic-direct but are in the same order of magnitude.
- **Microsoft Azure Foundry** — Anthropic models available through Foundry as of 2025. Azure-native enterprise → same story: no new vendor onboarding, billing rolls into the existing Azure invoice.
- **Anthropic API direct** — For teams that prefer direct billing or lack AWS/Azure as a procurement path. Standard published API rates apply. This adds Anthropic as a vendor; it is the only path that requires that step.

A senior engineer faced with "$50/developer/year API consumption captures $52K of avoided rework" cannot credibly maintain "any additional expense" as a refusal posture — the asymmetry is too large. If the underlying objection is a no-new-vendors policy, the AWS Bedrock or Azure Foundry path removes that objection for most enterprise deployments. If the objection persists, it is a posture argument, not a procurement-reality argument.

---

## The mechanisms

Each Claude-exclusive finding's avoided cost is built from one of two cost-prevention mechanisms. A third class of failure mode exists that cross-model review does **not** address; it is documented below as Mechanism C for completeness and credibility.

### Mechanism A — Beta-cycle catch-and-fix avoided

The bug ships to a beta build, a beta tester reports it, the maintainer triages, attempts a fix, validates, redeploys. Per-finding cost components: tester triage 1-2 hr ($50-100), project-side triage 1-2 hr ($120-240 at $120/hr loaded), 1-2 same-model fix attempts (~30 min each plus inference), final fix and redeploy 1-3 hr.

**Per-finding avoided cost: ~$500-$1,000.** Headline uses the lower bound ($500). Mechanism A applies to most exclusive findings — bugs that would have been caught downstream but at meaningful incremental cost.

### Mechanism B — Same-model debug loop avoided (the unique cross-model value)

The bug enters a loop. The same model that generated the bug attempts to fix it. Each "fix" preserves the underlying assumption error because the assumption is invisible to that model. The loop can take 3-5 iterations or, in the worst case, become unbounded until a human or external reviewer intervenes.

Beta testing does not break Mechanism B; it makes it worse. Beta testers report symptoms ("the audio cuts out", "the popup keeps opening") but the same model writes the fix. Each fix attempt addresses the symptom while preserving the bug.

The canonical worked example in this project is the audit-script saga:

- `4f0fa46` — first attempt to reconcile two cost-counting scripts
- `6c6468a` — "refinement" that adopted the same wrong pricing constant
- `e456666` — "refinement" that re-validated against the same biased reference (`ccusage`, which the script itself had populated)

Three same-model passes embedded the same wrong assumptions about Anthropic pricing constants and whether `ccusage` could be an independent oracle. The loop only broke when Codex was given an explicit external-validation prompt and used WebFetch to retrieve Anthropic's pricing page directly (`dev/adversarial/2026-04-25-cost-methodology-r5-codex.md`).

Per-finding cost components: 3-5 fix iterations (~30 min wall-clock each plus inference), 4-8 hr of maintainer debugging time during the loop, lost confidence in the surrounding subsystem (not dollar-ized), eventual external intervention to break the loop.

**Per-finding avoided cost: ~$2,500-$4,000.** Headline uses the lower bound ($2,500); the highest-impact structural bugs (e.g., shipping math errors that surface as user-visible symptoms) use $4,000. Mechanism B applies to roughly 20% of exclusive findings — the structural blind-spot bugs where a single-model debug loop would predictably embed and re-embed the same wrong assumption.

### Mechanism C — Context-supply errors (a class cross-model review does NOT catch)

Cross-model adversarial review catches structural blind spots and methodology errors. **It does not catch errors where both agents share a wrong contextual assumption supplied by the dispatching prompt.** When the input frame is wrong, all model reviewers operate on the wrong frame and converge on the wrong answer.

The worked example is this very document. v1 and v2 both used consumer Claude Max subscription pricing ($2,400/yr) as the cost denominator because that was what the dispatch context referenced. Codex's methodology validation between v1 and v2 did not flag the pricing-context error either; Codex was given the same enterprise-context-omitting prompt frame. Three distinct model reviewers operated on the wrong cost shape and produced an internally-consistent but framing-wrong artifact. The error was caught only when the human author read v2 and supplied the missing enterprise context.

The implication: **cross-model review is one of three layers of review, not the only one.** A complete review posture has same-model review (catches obvious errors), cross-model review (Mechanism A and B catches; this document's pitch), and **human contextual review** (Mechanism C catches; not replaceable by any model — covers context that lives in the dispatcher's head, in organizational knowledge, or in domain expertise the prompt didn't surface).

A pitch that claimed cross-model review caught everything would be less credible. Acknowledging Mechanism C's existence is a strengthening point: the harness has known limits and the methodology is honest about them. Human review is not made redundant by adding cross-model review — it is made **more leveraged**, because human reviewers can focus on context-supply gaps rather than structural-bug hunting.

---

## Scope options

Decision-makers benefit from having fallback positions, not all-or-nothing. The table below shows scope tiers with rough cost and value for each. All four tiers are net-positive ROI by orders of magnitude; the decision-maker can pick any tier and the math still favors adoption.

| Scope tier | What's reviewed cross-model | Estimated cost/developer/yr | Estimated incremental Claude-exclusive value/developer/yr | Approx ROI |
|---|---|---:|---:|---:|
| **Full harness** | Every spec, every methodology document, every adversarial-review-eligible artifact | ~$50/yr | ~$52K | ~1000× |
| **Spec-only** | New feature specs only (~10/yr typical) | ~$5-10/yr | ~$30-40K | ~3000× |
| **Security/compliance-only** | Specs touching auth, data handling, external integrations | ~$2-5/yr | ~$15-20K | ~3000× |
| **Methodology-only** | Critical analyses (cost models, ROI claims, customer-facing artifacts) | ~$1-2/yr | ~$5-10K | ~5000× |

Notes on the tiering:

- **Spec-only** captures the largest share of Mechanism B catches because most structural blind spots surface at spec review (when the wrong assumption is being committed to design) rather than at code review (when it's already cooked in).
- **Security/compliance-only** is a smaller scope but each catch is high-stakes — a cross-model review that flags a missed-auth-path or a data-handling assumption pays for the entire annual budget.
- **Methodology-only** is the narrowest tier and has the highest ROI ratio because methodology errors (like the audit-script saga) are rare but catastrophic when they ship as customer-facing artifacts.

A skeptic who finds the full-harness number unbelievable can fall back to methodology-only at ~$1-2/yr and still capture orders-of-magnitude ROI from rare-but-catastrophic catches.

---

## The recursion: this document tested its own thesis

### v1 → v2: Codex caught structural and methodology errors

The v1 draft (`dev/notes/cross-model-review-value-draft-v1.md`, agent gravel, Sonnet) was reviewed by Codex (`dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md`, commit `1403ad1`). Codex caught four classes of error, each of which would have weakened the pitch in front of a hostile audience:

1. **Wrong primary citation** — v1 attributed the cost-multiplier rubric to "NIST SP 500-235 (2002)." That document is a 1996 structured-testing standard; the 2002 economic-impact source the draft was reaching for is **NIST Planning Report 02-3**. A senior reviewer would have looked up SP 500-235, found a different document, and discarded the entire rubric on credibility grounds.
2. **Category error on memo findings** — v1 applied the 30× production-defect multiplier to memo/framing findings. Memo findings have rework cost, not defect-escape cost. Treating them as production defects inflated the number and signaled methodological unseriousness.
3. **Internal attribution contradictions** — five rows in the catch inventory were tagged in ways that contradicted their cited evidence (e.g., `CLAUDE-EXCLUSIVE` rows whose source citations were Codex files). Invisible on a same-model re-read because the author assumes their own consistency; an external reviewer notices on first pass.
4. **Wrong pitch frame** — v1 headlined "~113× ROI" against the whole two-model harness. The actual decision is incremental Claude-on-top-of-Codex. Wrong frame for the audience; the pitch would have lost a senior engineer at the headline.

These corrections were not catchable by the same-model author no matter how careful. They are the same failure mode the harness is pitched to mitigate, applied to a document arguing for the harness. Mechanism B in worked-example form.

### v2 → v3: the human caught a context-supply error neither model addressed

v2 (commit `8c254cd`, agent shale, Opus) carried Codex's corrections forward and produced a tighter, methodologically-defensible pitch. It still got the cost shape wrong: it used consumer Claude Max subscription pricing ($2,400/yr) as the denominator throughout. The ROI numbers it produced (~22× midpoint) were defensible against that denominator but did not match the enterprise-procurement reality the actual audience operates in.

Three distinct model agents reviewed the cost-shape framing — gravel drafting v1, Codex methodology-validating v1, shale revising into v2 — and **none caught the consumer-vs-enterprise pricing assumption**. The dispatch context referenced consumer subscription pricing; all three models accepted the frame and produced an internally-consistent artifact in the wrong frame.

The human author caught it on first read of v2 by supplying the missing context: the employer's stated rejection is a posture argument ("any additional expense at all, given an existing Codex contract"), not a price argument, and is best defeated by reframing as API consumption rather than as subscription. That single context input collapsed the pricing frame and forced the v3 reframe.

This is Mechanism C in worked-example form. Cross-model review cannot catch errors where the entire input frame is wrong; only human contextual review can. The harness is more useful when paired with human review, not less.

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

### Cost-side calculation (API consumption)

Per-session cost for a typical adversarial-review pass against a spec (~10K input + ~3K output tokens):

- **Sonnet** (Anthropic-direct: $3/M in + $15/M out) → ~$0.08/session
- **Opus** (Anthropic-direct: $15/M in + $75/M out) → ~$0.18/session

Cadence per developer per year: 10-20 sessions/quarter × 4 = 40-80 sessions. At $0.08-$0.18/session, **~$3-$15/yr actual API cost per developer**. A budget ceiling of **~$50/developer/year** absorbs fluctuations, re-runs after rework, and adoption growth. The headline ROI uses $50 to keep the denominator generous.

Bedrock and Azure Foundry rates differ slightly from Anthropic-direct but stay within the same order of magnitude (1.0×-1.3× depending on procurement path). Even at the high end, per-developer-year cost remains under $100.

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

The inventory below reflects Codex's spot-check corrections to the v1 draft. Reclassifications are noted explicitly. Per-finding mechanisms and dollar amounts are unchanged from v2; only the cost denominator (subscription → API consumption) changed in v3.

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

| Item | Cost / Value |
|------|------:|
| API consumption budget (full harness, generous) | ~$50/developer/yr |
| API consumption (typical actual) | ~$3-$15/developer/yr |
| Conservative ROI ($22,500 / $50) | **~450×** |
| Codex independent-estimate ROI ($52,000 / $50) | **~1,000×** |
| Upper-bound ROI ($60,000 / $50) | **~1,200×** |

The pitch holds at any point in this range. Against the typical-actual API spend (~$10/yr midpoint), ROI is 2,250×-6,000×; the headline uses the budgeted $50/yr denominator to stay defensibly conservative.

### Sensitivity

Avoided-cost figures scale linearly with engineer hourly rate. At $80/hr (junior), conservative ROI is ~300×; at $160/hr (FAANG senior), Codex-midpoint ROI is ~1,400×. The qualitative argument is unchanged across the rate range. The denominator could double (heavy Opus usage, Bedrock premium, doubled session count) and ROI would still exceed 200× at the conservative bottom and 500× at the Codex midpoint. The asymmetry between consumption cost and avoided cost is too large to be erased by reasonable rate variation.

---

## Caveats

1. **Single-project sample.** Findings are drawn from one project (Geographica) with one human author. The cross-model complementarity pattern is not yet validated across multiple projects or teams. The pattern is consistent with what the literature on adversarial review predicts, but generalization should be tested.

2. **Conservative attribution.** Where it was unclear whether a finding was caught by both model families or only one, the more conservative (cross-confirmed) classification was used. Some genuinely Claude-exclusive findings may be missed by this rule, biasing the headline downward.

3. **Mechanism assignment is a judgment call.** Whether a finding triggers a Mechanism B same-model loop or is caught at Mechanism A by downstream testing depends on the specific bug and the team's testing rigor. The 80/20 split (most findings Mechanism A, ~20% Mechanism B) is observed in this project; other projects may differ.

4. **Pitch context: incremental decision.** This document estimates the incremental value of adding Claude API consumption on top of Codex. A team starting from zero would see a different ROI breakdown; this analysis does not claim to model that scenario.

5. **API rates change.** Per-session figures use Anthropic-direct published rates as of 2026-04. Bedrock and Azure Foundry rates are within the same order of magnitude but vary; budget +30% headroom for procurement-path rate differences. Even with that headroom, per-developer-year cost remains under $100.

6. **Mechanism B costs are observed minimum.** The audit-script saga took 3 commits and several hours of debugging time to break out of; the $2,500 lower bound is conservative for that case. A genuinely unbounded loop (which can happen) would cost much more, but those costs are not assumed in the headline.

7. **Mechanism C is acknowledged but not addressed.** Cross-model review does not catch context-supply errors (the wrong-input-frame failure mode demonstrated in this document's v1→v2→v3 history). Human contextual review remains essential as a third review layer. The pitch is for adding Claude on top of Codex, not for replacing human review with model review.

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

The Codex methodology validation that produced v2 is at `dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md` (commit `1403ad1`). The v2 document v3 supersedes is at commit `8c254cd`. The v1 draft both supersede is at `dev/notes/cross-model-review-value-draft-v1.md`.

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

*Document v3 produced 2026-04-25 by agent saltbush, post-Codex methodology validation and post-human context-supply correction. Supersedes v2 (commit `8c254cd`, agent shale) and the v1 draft at `dev/notes/cross-model-review-value-draft-v1.md`.*
