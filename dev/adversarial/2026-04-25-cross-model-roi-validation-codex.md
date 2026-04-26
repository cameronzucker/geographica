2026-04-25T20:35:58.089101Z ERROR codex_core::codex: failed to load skill /home/administrator/Code/agent-skills/plugins/project-setup/skills/claude-agents-md-init/SKILL.md: invalid description: exceeds maximum length of 1024 characters
OpenAI Codex v0.118.0 (research preview)
--------
workdir: /home/administrator/Code/geographica
model: gpt-5.4
provider: openai
approval: never
sandbox: read-only
reasoning effort: none
reasoning summaries: none
session id: 019dc65b-3273-7f63-8027-f8678acff129
--------
user
You are conducting an independent methodology validation of a cross-model adversarial-review ROI analysis. The analysis is at:

  /home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md

The author of this analysis is a Claude Sonnet agent. Your role as Codex (OpenAI) is the cross-model defensibility check — would you, an independent reasoner with a different mental model, accept this analysis if shown it as evidence?

## Read these files in /home/administrator/Code/geographica/

- dev/notes/cross-model-review-value-draft-v1.md (the analysis itself)
- dev/adversarial/2026-04-25-cost-methodology-r5-codex.md (your own prior cost-methodology review — for context on how Codex-flagged findings get classified)
- Sample one or two adversarial files from each cycle to spot-check the exclusivity classification:
  - dev/adversarial/2026-04-24-ruler-r5-codex.md
  - dev/adversarial/2026-04-24-ruler-r1-architectural.md
  - dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md
  - dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md

## Context

The analysis claims ~$297,600 in avoided downstream cost from "exclusive" catches (findings caught only by Codex or only by Claude, where the other model demonstrably missed them) across 6 fully-comparable adversarial cycles. The pitch this analysis supports is being made to a senior engineering team that currently has OpenAI/Codex but is being asked to add Claude Premium for cross-model coverage.

Defensibility is the goal. Cherry-picking, sloppy attribution, or weak cost rubric will get caught.

## Your job

Produce an independent methodology validation. Specifically attack:

1. **Rubric soundness.** The analysis cites NIST SP 500-235 (2002), Capers Jones (1997), IBM Systems Sciences Institute. Are these cited correctly? Are the multipliers (1× spec-review, 5× MAJOR-shipped, 30× CRITICAL-shipped) within the defensible range these sources support? Are the loaded engineer-hours estimates per category reasonable?

2. **Attribution honesty.** Spot-check 3-5 specific "CODEX-EXCLUSIVE" or "CLAUDE-EXCLUSIVE" findings by reading the actual review files. Is the attribution accurate? Did the supposedly-missed-by-the-other-model finding actually appear in the other model's review (perhaps in different words)?

3. **Production-multiplier defensibility.** Caveat #1 in the analysis says the 30× multiplier only applies to findings "that would have survived plan-writing and implementation." Walk a few specific findings — e.g., the cost-methodology pricing constants, the TTM `distanceToManeuver` signed-return bug — and assess whether they would ACTUALLY have shipped to production, or whether they would likely have been caught later by some other mechanism.

4. **Anything else a Codex-trained reviewer would catch that a Claude reviewer wouldn't think to question.**

## Independent estimate

After your methodology review, produce your own ROI estimate using whatever assumptions you find most defensible. If your number is within 50% of $297,600, that's strong cross-model consensus. If it's wildly different, explain why.

## Output format

# Codex methodology validation — cross-model review value analysis

**Reviewer model:** [your model]
**Date:** 2026-04-25
**Scope:** independent methodology review of dev/notes/cross-model-review-value-draft-v1.md
**Author of analysis under review:** Claude Sonnet (agent moniker: gravel)

## Verdict

[ACCEPTABLE AS-IS | ACCEPTABLE WITH MINOR REVISIONS | NEEDS MAJOR REVISION | METHODOLOGY UNSOUND]

## Methodology assessment

- Rubric basis: [your evaluation]
- Cost multipliers: [your evaluation]
- Engineer-hour estimates: [your evaluation]

## Attribution spot-checks (3-5 findings)

[For each finding, state: which file you read, whether the exclusive attribution is accurate, your reasoning]

## Production-multiplier defensibility

[Walk 2-3 findings, assess whether they would have actually shipped]

## Independent ROI estimate

[Your number, with reasoning]

## What the analysis does well

[List]

## Where it could be strengthened (if anything)

[List]

## Pitch-defensibility assessment

[Would you, as a hostile senior engineer, accept this analysis as evidence? Why or why not?]

## Output destination

Save your full validation to: dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md

codex
The task is a methodology review of the ROI draft plus spot-checking the underlying adversarial files. The obvious route here would be the repo’s `review` skill, but that skill is not available in this session, so I’m proceeding with a direct file-based validation and will keep the focus on defensibility rather than agreement.
exec
/bin/bash -lc "sed -n '1,260p' dev/notes/cross-model-review-value-draft-v1.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
# Cross-model adversarial review — quantified value

> Pitch-ready ROI analysis for adopting cross-model adversarial review on
> top of existing single-model coding-assistant infrastructure.
>
> Prepared: 2026-04-25 · Agent: gravel · Source data: dev/adversarial/ (40 files)

---

## TL;DR for decision-makers

- Across 8 distinct review cycles covering navigation, voice, measurement, and cost methodology, the cross-model harness surfaced **41 exclusively model-specific critical findings** — 16 caught only by Codex (OpenAI) and 25 caught only by Claude rounds — that the other model did not surface.
- Using conservative bug-cost rubric (NIST SP 500-235 / IBM Systems Sciences Institute, 2002), exclusive-catch findings represent **$297,600 in avoided downstream work** that single-model review would have missed.
- The harness costs **$2,640/yr** per developer (Claude Max + ChatGPT Plus). The avoided-cost ROI is **~113× annual subscription cost**.
- The pitch does not rest on "Claude vs. OpenAI." Both models are capable. The evidence shows each model's architecture creates predictable blind spots that the other consistently fills — the value is in the *combination*, not the individual models.
- Top Codex-exclusive catches: (1) cost-methodology pricing constants wrong by 3× (output token double-count compounds to 5.6× inflation); (2) editing-state click leakage into reverse-geocode handler; (3) spec-wide internal inconsistency — NoSleep architecture still embedded after R1-R5 invalidated it. Top Claude-exclusive catches: (1) cache-write exclusion unjustified by the methodology's own standard (framing hole); (2) `ccusage` cited as validation but cannot validate itself; (3) negative `distanceToManeuver` returns pass every TTM threshold.

---

## Methodology

### Rubric basis

Bug-cost multipliers follow the NIST Special Publication 500-235 (2002), "The Economic Impacts of Inadequate Infrastructure for Software Testing," and the IBM Systems Sciences Institute study (cited in that publication) that established the canonical bug-cost-by-phase curve:

- A defect found during design/spec review costs **~1× engineer-day** to fix.
- The same defect found in integration testing costs **~6–10×** more.
- The same defect reaching production costs **~30–100×** more, due to triage, hotfix deployment, communication, and data remediation.

Source: Capers Jones, *Software Quality: Analysis and Guidelines for Success* (1997), cross-referenced in NIST SP 500-235 §5.3. The IBM SSI paper is widely republished as "the cost to fix a bug grows 5x-10x per phase"; the NIST survey anchors the 30× production multiplier.

This analysis uses the **conservative end** of every range. No finding is assigned the 100× multiplier; CRITICALs shipped to production are capped at 30×.

### Cost rubric (all figures in USD)

```
Avoided cost = severity_multiplier × loaded_engineer_hours × $120/hr

severity_multiplier:
  CRITICAL bug caught at spec review:       1×   (finding in review prevents the multiplier)
  MAJOR bug caught at spec review:          1×
  CRITICAL bug that would ship:            30×   (NIST production multiplier)
  MAJOR bug that would ship:                5×

loaded_engineer_hours per category:
  Math / calculation / pricing error:       8h
  Framing / documentation bug:              4h
  API / behavioral correctness:            12h
  Concurrency / race condition:            16h
  Data integrity / security:               24h
  Spec internal inconsistency:              6h   (misleads implementer, causes rework)
```

The $120/hr rate is conservative for a senior engineer, fully loaded (benefits, overhead, opportunity cost). Industry median in 2025 for a software engineer is $80–$160/hr depending on market; $120 is the geometric mean of that range.

### Attribution rules

A finding is classified:

- **CODEX-EXCLUSIVE** if it appears in the Codex round (R5 or R6) and is absent from all parallel Claude rounds for that cycle.
- **CLAUDE-EXCLUSIVE** if it appears in ≥1 Claude round and is absent from the Codex round.
- **CROSS-CONFIRMED** if caught independently by both model families (same finding identified without one influencing the other).
- **CONSENSUS** if caught by all reviewers regardless of model.

When in doubt, the conservative classification is used (CROSS-CONFIRMED over CODEX- or CLAUDE-EXCLUSIVE).

Rounds R1–R4 (all Claude) are the "Claude side." Rounds R5–R6 are "Codex side" (Codex CLI via OpenAI gpt-5.4 / ChatGPT-auth mode).

---

## The catch inventory

### Cycle 1: Cost methodology (2026-04-25)

**Reviewers:** R1 (Claude/wren), R2 (Claude/basalt), R3 (Claude/flint), R5 (Codex)  
**Note:** R1, R2, and R5 are classified separately despite addressing overlapping topics, because they ran independently. R1 is primarily a math/pricing lens, R2 a coverage/sampling lens, R5 a cross-model pricing verification lens.

| ID | Severity | Exclusivity | Avoided cost | Description |
|----|----------|-------------|-------------|-------------|
| CM-C1a | CRITICAL | CODEX-EXCLUSIVE | $28,800 | Opus 4.x pricing constants wrong by 3×: $15/$75 vs correct $5/$25; Codex independently fetched Anthropic pricing docs and verified against LiteLLM DB. Claude rounds (R1, R2) confirmed after-the-fact that they had _not_ cross-checked against a live source before Codex did. R5 is the first file to cite a specific dollar-verified cross-check using ccusage token counts. *File: 2026-04-25-cost-methodology-r5-codex.md* |
| CM-C1b | CRITICAL | CROSS-CONFIRMED | — | Same pricing error (R1 and R2 both caught it; R1 cites Anthropic docs, R2 cites LiteLLM). Classified CROSS-CONFIRMED; not counted in exclusive ROI. |
| CM-C2 | CRITICAL | CODEX-EXCLUSIVE | $28,800 | Output tokens double-counted due to streaming partial records; dedup by message.id required; net inflation 5.6× compound with C1. Codex identified via transcript-format analysis from an OpenAI-transcript-protocol perspective; Claude R1/R2/R3 did not surface this. *File: 2026-04-25-cost-methodology-r5-codex.md* |
| CM-C3 | CRITICAL | CLAUDE-EXCLUSIVE | $5,760 | Cache-write exclusion from headline is unexplained; by the methodology's own standard, cache writes are billable compute work and should be in the headline. Hostile-reader framing. *File: 2026-04-25-cost-methodology-r3-framing.md (C1)* |
| CM-C4 | CRITICAL | CLAUDE-EXCLUSIVE | $5,760 | "Matches ccusage" is appeal-to-tool, not appeal to billing truth; ccusage cannot independently validate numbers it contributed to computing. *File: 2026-04-25-cost-methodology-r3-framing.md (C2)* |
| CM-C5 | CRITICAL | CLAUDE-EXCLUSIVE | $5,760 | Cache-reads-as-harness-artifact is asserted without argument; a hostile reader can rebut it immediately; three sub-objections enumerated. *File: 2026-04-25-cost-methodology-r3-framing.md (C3)* |
| CM-M1 | MAJOR | CROSS-CONFIRMED | — | `model_tier()` too coarse; mixed-generation corpora mis-priced. Both R1 and R2 flagged. |
| CM-M2 | MAJOR | CLAUDE-EXCLUSIVE | $3,840 | Codex usage (30 sessions, gpt-5.4) documented in `~/.codex/sessions/` is real but absent from methodology disclosure; creates a reproducibility gap. *File: 2026-04-25-cost-methodology-r2-coverage.md (M1)* |
| CM-M3 | MAJOR | CROSS-CONFIRMED | — | Spec's stated dollar figures ($2,489/$21,858) do not match script output at any pricing assumption; both R1 and R2 flagged. |
| CM-M4 | MAJOR | CLAUDE-EXCLUSIVE | $3,840 | "Anyone can reproduce" overstates reproducibility — only Cameron can run the script against his private transcript directory; external auditors cannot. *File: 2026-04-25-cost-methodology-r3-framing.md (M3)* |

**Cycle 1 subtotals:**
- CODEX-EXCLUSIVE: 2 CRITICAL → $57,600
- CLAUDE-EXCLUSIVE: 3 CRITICAL + 2 MAJOR → $24,960
- CROSS-CONFIRMED/CONSENSUS: not counted in exclusive ROI

---

### Cycle 2: Ruler/measurement tool (2026-04-24)

**Reviewers:** R1 (Claude/cholla), R2 (Claude/cholla), R3 (Claude/cholla), R4 (Claude/cholla), R5 (Codex)

| ID | Severity | Exclusivity | Avoided cost | Description |
|----|----------|-------------|-------------|-------------|
| RL-C1 | CRITICAL | CONSENSUS | — | Terrain-RGB decode formula wrong (Mapbox vs Terrarium); caught independently by R1, R2, and R4 before Codex ran. All Claude rounds caught it. |
| RL-C2 | CRITICAL | CONSENSUS | — | `useImperial` closure snapshot produces stale unit after toggle; caught by R1 and R4. |
| RL-C3 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | Editing-state vertex clicks leak into reverse-geocode handler: `isActive()` returns false in `editing` state, so the app.js L1622 suppression does not fire; every vertex-select tap also opens a reverse-geocode popup. R1-R4 each caught the `isActive()` boundary but none independently identified this specific leakage path. Codex traced the actual `queryRenderedFeatures` exclusion list at L1622-1635 and found ruler layers were absent. *File: 2026-04-24-ruler-r5-codex.md (C1)* |
| RL-M1 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Style-load reattach pattern doesn't match cited precedent; layer-ordering race with `_enforceImageryOrder()`; R1 traced the MapLibre listener insertion-order semantics. *File: 2026-04-24-ruler-r1-architectural.md* |
| RL-M2 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Missing `text-font` declaration in `ruler-vertex-labels` symbol layer; offline tileserver only serves Metropolis+Noto; labels render blank. R1 traced `tileserver/fonts-served/` directory. *File: 2026-04-24-ruler-r1-architectural.md* |
| RL-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Bootstrap ordering: `initRuler()` must run after `initSidebarTabs()` and before `restoreLastSidebarTab()` — specific sequence not specified; race causes `clear()` not to fire on persisted-tab restoration. *File: 2026-04-24-ruler-r1-architectural.md* |
| RL-M4 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Index panel class naming drift: spec says `class="sidebar-panel hidden"` but codebase uses `class="panel"` + `.active`; spec implementation would be invisible regardless of state. *File: 2026-04-24-ruler-r1-architectural.md* |
| RL-M5 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Tile cache decoded-pixel size understated (192KB/tile claimed, actual is 256KB RGBA); ImageBitmap retention doubles worst-case memory; no LRU eviction policy → unbounded session growth. *File: 2026-04-24-ruler-r2-scale-performance.md (F2.4, F2.9)* |
| RL-M6 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | z=12 sample zoom claims "~9.5 m/px at AZ latitude" — actual is ~32 m/px; error is 3.4×; invalidates 50-tile cap rationale, sample spacing logic, and the entire "Why z=12" justification. *File: 2026-04-24-ruler-r2-scale-performance.md (F2.2)* |
| RL-M7 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Vertex hit targets (16px diameter) fail WCAG 2.5.5 and Apple HIG 44px minimum; invisible 44px hit-area layer not specified; feature is demonstrably unusable with gloves. *File: 2026-04-24-ruler-r3-ux-mobile-a11y.md (CRITICAL-1)* |
| RL-M8 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | `#ruler-mode-banner` collides physically with `#nav-banner` (full-width, z-index 18); nav-active + ruler-active is a real workflow; spec defers without resolution. *File: 2026-04-24-ruler-r3-ux-mobile-a11y.md (CRITICAL-3)* |
| RL-M9 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Font stack wrong relative to actual style corpus: spec says `['Metropolis Regular']` but all three shipped basemap styles use `['Metropolis Regular', 'Noto Sans Regular']`; brittle glyph fallback. R1 had partially caught this (same finding root), but Codex traced all three tileserver style files independently. *File: 2026-04-24-ruler-r5-codex.md (M3)* |
| RL-M10 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Terrarium decode guard missing: `(0,0,0)` decodes to −32,768 m and will dominate min/max/gain; spec says "compute on non-null samples" but never defines when a sample is null; R1-R4 noted the formula fix but none added the sentinel guard. *File: 2026-04-24-ruler-r5-codex.md (M4)* |
| RL-M11 | MAJOR | CODEX-EXCLUSIVE | $5,760 | app.js integration insert-count claimed as "5 inserts + 1 whitelist edit" but the `addPlaceholderSources()` style-load hook is a 6th edit not in the count; also, editing-state click fix (C3) adds another; scope misrepresented, merge-risk analysis wrong. *File: 2026-04-24-ruler-r5-codex.md (M2)* |

**Cycle 2 subtotals:**
- CODEX-EXCLUSIVE: 1 CRITICAL + 3 MAJOR → $60,480
- CLAUDE-EXCLUSIVE: 8 MAJOR → $46,080
- CONSENSUS/CROSS-CONFIRMED (C1, C2): not counted

---

### Cycle 3: Nav-voice TTM redesign (2026-04-20)

**Reviewers:** R1 (Claude), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Claude/product), R6 (Codex)

| ID | Severity | Exclusivity | Avoided cost | Description |
|----|----------|-------------|-------------|-------------|
| TTM-C1 | CRITICAL | CLAUDE-EXCLUSIVE | $43,200 | `distanceToManeuver` returns signed values; negative TTM passes every threshold; far-tier fires for already-executed maneuvers. R6 (Codex) did not surface this specific arithmetic hazard. *File: 2026-04-20-nav-voice-ttm-r1-api-correctness.md (F1.1)* |
| TTM-C2 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | `start()` does not run the TTM pipeline on activation; G2 and G4 spec guarantees ("1 prompt per maneuver at route-start") are structurally false because `checkVoice()` is never called on start; `currentManeuverIdx` left at 0 on mid-route start → wrong next-maneuver announced. Claude R1-R5 focused on `tick()` path exclusively. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.1)* |
| TTM-C3 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | "No nav-ui changes" spec claim (NG3/G9) becomes structurally false if start-time voice is implemented to satisfy G2/G4: first prompt fires before mute-sync and before speech priming, because `nav-ui.js:154-161` initializes mute after `nav.start()`. Both guarantees cannot simultaneously be true in the existing architecture. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.2)* |
| TTM-M1 | MAJOR | CODEX-EXCLUSIVE | $5,760 | "3-maneuver route → 3 spoken prompts" test is off by one: engine voices the **upcoming** maneuver; a 3-maneuver route produces at most 2 spoken prompts under current semantics. Claude rounds wrote tests that would validate against the wrong maneuver semantics. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.3)* |
| TTM-M2 | MAJOR | CODEX-EXCLUSIVE | $5,760 | G7 "behavior is deterministic" is false: `tick()` uses `Date.now()` repeatedly; stale-GPS voice is generated by a 1Hz interval; `updateGPS()` stamps `lastGPSTime = Date.now()` not the GPS timestamp field. Same route+GPS sequence with different inter-arrival timing produces different voice output. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.4)* |

**Cycle 3 subtotals:**
- CODEX-EXCLUSIVE: 2 CRITICAL + 3 MAJOR → $103,680
- CLAUDE-EXCLUSIVE: 1 CRITICAL → $43,200

---

### Cycle 4: Nav wake-lock / keep-awake (2026-04-20)

**Reviewers:** R1 (Claude), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Claude/product), R6 (Codex)

| ID | Severity | Exclusivity | Avoided cost | Description |
|----|----------|-------------|-------------|-------------|
| WL-C1 | CRITICAL | CODEX-EXCLUSIVE | $14,400 | Spec is structurally inconsistent: R1 invalidated NoSleep.js architecture but the spec still names `frontend/vendor/nosleep.min.js`, `window.NoSleep`, NoSleep-specific tests, and the appendix justifying NoSleep v0.12.0. A subagent following the written spec would reintroduce the rejected dependency. No prior Claude round synthesized across all spec sections to catch this whole-spec inconsistency. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.1)* |
| WL-C2 | CRITICAL | CODEX-EXCLUSIVE | $14,400 | "Silent video" helper is underspecified: an MP4 with an audio track of silence (vs no audio track at all) interacts differently with autoplay policy, media sessions, and the co-active `speechSynthesis` + `getUserMedia` APIs. On iPhone-in-vehicle, the wrong spec causes the fallback to require stricter user activation than expected. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.4)* |
| WL-M1 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Bespoke HTTP fallback needs CSP/Permissions-Policy contract: `blob:` or `data:` media requires explicit `media-src` allowance; future security hardening silently breaks the primary AREDN (HTTP) path. Claude rounds focused on API behavior, not browser-policy surfaces. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.2)* |
| WL-M2 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Injected `<video>` can leak into accessibility tree without `aria-hidden="true"` + `tabindex="-1"`; adds ghost media control to TalkBack/VoiceOver rotor during navigation. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.3)* |
| WL-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Safety framing is load-bearing but imprecise: the causal chain "screen dims → nav stops → driver endangered" is wrong; the real risk is driver distraction from checking a dark phone. Sharpening the framing disciplines the scope: explains why G4 (no UI chrome) and NG3 (no alarms on backgrounding) are correct choices. *File: 2026-04-20-nav-keep-awake-r5-product.md (F5.1)* |

**Cycle 4 subtotals:**
- CODEX-EXCLUSIVE: 2 CRITICAL + 3 MAJOR → $46,080
- CLAUDE-EXCLUSIVE: 1 MAJOR → $5,760

---

### Cycle 5: Nav voice TTM follow-up (2026-04-24)

**Reviewers:** R1 (Claude/pinyon-sub-r1), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Codex)

| ID | Severity | Exclusivity | Avoided cost | Description |
|----|----------|-------------|-------------|-------------|
| FU-C1 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | BFCache diagnosis overstated; proposed `pageshow persisted=true` listener does not cover tab-discard, renderer-recreation, or standalone-PWA process recreation return paths; fix can ship while the user-visible bug remains reproducible on non-BFCache return paths. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.2)* |
| FU-C2 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | GPS-dropout recovery unspecified: after stale GPS + dead reckoning, the first recovered tick can fire a sharply-different prefix from what the driver expected (e.g., "now turn" vs "in quarter mile") with no stale/recovery guard. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.4)* |
| FU-M1 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Net Issue-1 buffer gain at 25 mph is only +0.6 s after Issue-2 prefix cost, not +1.3 s as claimed in §4.2; 0.6 s is inside the driver-reaction envelope (0.8–1.5 s); spec G1 "≥2.8 s post-speech buffer" is not met. Known-wrong number left in spec body with correction buried in §9. *File: 2026-04-24-nav-voice-followup-r1-api-correctness.md (F1.3)* |
| FU-M2 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Band-boundary test vector (290m → "In 1000 feet") is numerically ambiguous: implementer's natural "round then band-check" yields "In 1/4 mile," not "In 1000 feet"; test will fail; spec body and implementation are inconsistent on which check runs first. *File: 2026-04-24-nav-voice-followup-r1-api-correctness.md (F1.10)* |
| FU-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Repeating same maneuver with two different live distances creates ambiguity: drivers interpret second prompt as correction, not escalation; no spec rule distinguishes far-tier-already-fired from fresh far-tier. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.3)* |
| FU-M4 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Restoring tab via synthetic `.click()` can blur active form input (e.g., route-start field) on BFCache return; route-regeneration behavior may trigger unexpectedly. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.7)* |

**Cycle 5 subtotals:**
- CODEX-EXCLUSIVE: 2 CRITICAL → $86,400
- CLAUDE-EXCLUSIVE: 4 MAJOR → $23,040

---

### Cycle 6: Nav voice picker (2026-04-21)

**Reviewers:** R1 (Claude), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Codex)

| ID | Severity | Exclusivity | Avoided cost | Description |
|----|----------|-------------|-------------|-------------|
| VP-C1 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | Cloud-backed voices (`localService === false`) are included in the spec's voice list without warning; on an isolated AREDN mesh these voices silently stop speaking; preference feature becomes a field failure mode. Claude rounds focused on API correctness, not network-topology constraints. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.1)* |
| VP-C2 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | Custom `button role="radio"` widget lacks required keyboard interaction model: single tabbable item, arrow-key navigation, Space activation, roving tabindex. ARIA attributes are present but behavioral parity is absent; screen-reader and keyboard users get non-conforming behavior. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.2)* |
| VP-M1 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Auto-preview speaks over assistive-tech output: for VoiceOver/TalkBack, changing voice selection triggers immediate `speechSynthesis.speak()` at the exact moment screen reader announces the focused control; two speech channels overlap. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.3)* |
| VP-M2 | MAJOR | CODEX-EXCLUSIVE | $5,760 | `utterance.lang = 'en-US'` hard-coded even when user selects `en-GB`/`en-AU`/`en-IN` voice; inconsistent locale tag asked of engine vs chosen voice; preview text uses US-centric street naming for non-US English locales. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.4)* |
| VP-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | `activePreviewUtterance` cleanup relies on `onend` event; W3C spec is explicit that cancelled utterances fire `onerror` only (`"interrupted"` or `"canceled"`), never `onend`; cleanup leaks; next `visibilitychange` kills the nav audio in flight. *File: 2026-04-21-nav-voice-picker-r1-api-correctness.md (F1.1)* |
| VP-M4 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | 5-second empty-voice fallback collapses three different states (no Speech API, voices not yet enumerated, gate on user gesture) into one permanent "not supported" message; operators on mesh interpret as platform limitation rather than recoverable delay. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.6)* |

**Cycle 6 subtotals:**
- CODEX-EXCLUSIVE: 2 CRITICAL + 2 MAJOR → $97,920
- CLAUDE-EXCLUSIVE: 1 MAJOR + 1 MAJOR → $11,520

---

### Cycles 7 & 8: April 16 pipeline reviews (2026-04-16)

**Reviewers:** Claude only (5 parallel lenses; no Codex round in these cycles)  
**Note:** No Codex round was run for the NOAA pipeline review cycles. These are Claude-only catches that represent the baseline value of running Claude reviews at all — not cross-model exclusivity catches.

These cycles are excluded from the exclusive-catch ROI calculation because cross-model comparison requires both sides to be present. They are mentioned for completeness: 40+ findings across concurrency, data integrity, error handling, memory, and performance. None can be classified CODEX-EXCLUSIVE or CROSS-CONFIRMED without a Codex round to compare against.

---

## ROI summary

### Per-exclusivity subtotals

| Category | CRITICAL findings | MAJOR findings | Avoided cost |
|----------|-------------------|----------------|-------------|
| CODEX-EXCLUSIVE | 12 | 10 | $204,960 |
| CLAUDE-EXCLUSIVE | 4 | 11 | $92,640 |
| **Total exclusive** | **16** | **21** | **$297,600** |

CROSS-CONFIRMED and CONSENSUS findings (those caught by both model families independently) are excluded from this table. By definition, single-model review would have caught those eventually — they are not the basis of the cross-model pitch.

### Annual cost vs avoided cost

| Item | Cost |
|------|------|
| Claude Max subscription | $2,400/yr |
| ChatGPT Plus (Codex CLI) | $240/yr |
| **Total harness cost** | **$2,640/yr** |
| **Avoided cost (exclusive catches only)** | **$297,600** |
| **ROI multiple** | **~113×** |

The ROI is overdetermined: even if two-thirds of the exclusive findings are discounted as "would have been caught eventually by QA or user testing," the remaining one-third still represents $99,200 in avoided cost — a 38× return.

---

## Caveats and what this analysis does NOT claim

1. **Not all CRITICAL findings were certain to ship.** Some CRITICALs are spec-phase catches on a design that would have been further reviewed before implementation. The 30× production-bug multiplier is used conservatively only for findings that would have survived plan-writing and implementation (e.g., the TTM `start()` gap, the Terrarium formula, the pricing constants — all were present in the code or in near-final specs ready for implementation).

2. **"Exclusive" attribution is best-effort, not proof.** The classification relies on the written review outputs. It is possible that a Claude reviewer noticed a finding but chose not to surface it, or that a Codex reviewer was influenced by having access to earlier Claude output in the file system (Codex reads the repo). Conservative attribution is used throughout.

3. **Avoided-cost calculation assumes the bugs would have shipped without the harness.** In practice, some would have been caught in integration testing, user testing, or beta feedback. The NIST multipliers represent what bugs cost on average when they reach production, which is the appropriate baseline for the cost-of-not-reviewing calculation.

4. **This does not claim Claude is better than Codex or vice versa.** The data shows each model has architectural strengths that the other lacks. Codex finds: cross-repo consistency checks, API contract violations against real-world browser docs, network-topology constraints (AREDN offline reality). Claude finds: framing defensibility, mathematical buffer calculations, spec-to-codebase discrepancies in format and API surface.

5. **The $120/hr rate is a single-point estimate.** At $80/hr (conservative junior engineer), ROI is ~75×. At $160/hr (senior/FAANG), ROI is ~226×. The pitch holds at any reasonable rate.

6. **Hardware costs are excluded.** The Pi 5 development machine ($150–$200) is a one-time cost not included in the $2,640/yr subscription figure.

---

## Reproduction

Every finding row in this document links to a specific file and heading in `dev/adversarial/`. To audit a claim:

1. Open the referenced file.
2. Find the heading matching the finding ID.
3. Verify the "Exclusivity" classification by searching other files in the same cycle for the same finding description.
4. Apply the cost rubric from the Methodology section.

The classification "CODEX-EXCLUSIVE" can be verified by searching the four Claude-round files for any mention of the specific finding. None of the CODEX-EXCLUSIVE findings listed here appear in the Claude-round files for that cycle.

exec
/bin/bash -lc "sed -n '1,260p' dev/adversarial/2026-04-24-ruler-r1-architectural.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
# Ruler spec — adversarial review R1: architectural / API soundness

**Reviewer:** Agent cholla, R1
**Spec under review:** `docs/superpowers/specs/2026-04-24-ruler-design.md`
**Lens:** Architectural / API soundness
**Date:** 2026-04-24

## Summary

The spec is well-structured and the IIFE module pattern is the right call.
However, there are **three CRITICAL architectural flaws** that will cause
the implementation to be wrong-out-of-the-gate or break under existing
codebase invariants:

1. The Terrain-RGB decode formula is for **Mapbox encoding** but the
   project's elevation tiles are **Terrarium encoding**. Decoded
   elevations will be off by ~32,000 meters across the entire map.
2. `formatNavDistance` lives in `nav-ui.js`, not `app.js` — so the
   proposed `_appAPI` export from app.js will fail to export it without
   cross-module hoisting that the spec doesn't describe.
3. `useImperial` is a closure-scoped `var` inside the app.js IIFE; the
   existing precedent (`navigation.js:1032`) is to expose it as a
   **live getter** that reads `window._geographicaUseImperial` at call
   time. Snapshot-on-init semantics — which the spec hints at by saying
   "explicit object" of values — would break unit-toggle live-updates.

There are also several MAJOR architectural concerns around state-machine
holes, init/bootstrap ordering, and DOM/CSS-class naming drift. The
data-shape "KMZ-serializable" claim mostly holds; the style-load reattach
pattern claim is loose-but-OK.

Net: the spec needs a focused revision pass on §A "Module layout & data
shape" and §E.3 "Elevation sampling" before plan-writing. The other
sections can be patched in-place from this review's recommended edits.

## Findings

### CRITICAL: Terrain-RGB decode formula is wrong for this codebase

**Spec lines:** §E.3 L181-184.

The spec uses the Mapbox Terrain-RGB decode:
```js
return -10000 + ((r * 65536 + g * 256 + b) * 0.1);   // meters
```

But the project's elevation tiles are **Terrarium-encoded** (Mapzen / AWS
Open Terrain Tiles). Evidence:

- `scripts/download_elevation.py:39` — pulls from
  `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
- `scripts/download_elevation.py:241` — MBTiles description literally
  says "Terrarium encoding"
- `frontend/app.js:325, 334` — both `addSource` calls set
  `encoding: 'terrarium'`

The two formulas give **different absolute elevations**:

| Encoding | Formula | Sample (R=128, G=0, B=0) |
|---|---|---|
| Mapbox Terrain-RGB | `-10000 + (R*65536 + G*256 + B) * 0.1` | 828.8 m |
| Terrarium | `(R*256 + G + B/256) - 32768` | 0 m |

If shipped as written, every `elevation_m` value will be off by
~32,000 m (with sign and slope structure preserved, so gain/loss
might still look "directionally right" on a sparkline). The headline
**min / max** numbers in the stats grid will be visibly absurd
("min: -31,500 m, max: -30,200 m"). gain / loss will be the only
correct numbers (since they're diff-based and the constant offset
cancels), masking the bug if you only test those two metrics.

**Recommended fix:** Replace §E.3 decode block with:
```js
function elevationFromRGB(r, g, b) {
  // Mapzen / AWS Open Terrain "terrarium" encoding — matches
  // the encoding declared in app.js:325/334 and the source pipeline
  // at scripts/download_elevation.py:39.
  return ((r * 256) + g + (b / 256)) - 32768;
}
```

And add a sanity-check fixture to `test_terrain_rgb.js`: a sample tile
pixel from a known peak (e.g. South Mountain summit at known elevation
~810 m) decoded against this function should round to within ±5 m.
This catches "wrong formula picked from web search" regressions.

---

### CRITICAL: `formatNavDistance` lives in `nav-ui.js`, not `app.js`

**Spec lines:** §A L54 — "collect `useImperial`, `formatRouteDistance`,
`formatNavDistance`, `haversineDistance`, `formatDD` into an explicit
object" *exported by app.js*.

`grep -n "function formatNavDistance"` shows the function is defined at
`frontend/nav-ui.js:800`, not in app.js. Both modules are separate IIFEs —
nav-ui.js cannot reach a closure-scoped function in app.js, and vice
versa. The spec's `window._appAPI` export from app.js cannot include
`formatNavDistance` without one of:

a. Duplicating the function inside app.js (technical debt — two
   sources of truth for nav-distance formatting; a future tweak to one
   silently doesn't propagate to the other).

b. Pre-existing nav-ui.js exposing it on `window` (it doesn't —
   `grep -n "window.*formatNavDistance"` returns nothing across the
   frontend tree). Adding this export is a small extra change to
   nav-ui.js the spec doesn't list.

c. Ruler.js reading it from a separate `window._navAPI` (implies
   creating a second API surface, which somewhat defeats the
   "consolidate into one object" framing).

This is not a hypothetical — without resolving it, ruler.js cannot
implement the headline distance readout per the spec.

**Recommended fix:** Pick one of:
1. **Preferred:** ruler.js reuses `formatRouteDistance` only (it's in
   app.js; close enough semantically — both render meters in the user's
   unit system). Drop `formatNavDistance` from `_appAPI`. Document why
   in §E (formatNavDistance has feet/yards-vs-miles cutover at
   different threshold than route formatter; ruler matches the route
   panel's cutover, not nav UI's).
2. Add a second insertion point to the spec: "**Insertion 2b.** in
   `nav-ui.js`, expose `formatNavDistance` as
   `window._navAPI = { formatNavDistance }`. ruler.js then consumes
   from both `_appAPI` and `_navAPI`."
3. Refactor nav-ui.js's formatNavDistance into a shared
   `frontend/units.js` (largest change; cleanest result; out of scope
   for ruler v1).

This decision has a downstream test impact — `test_unit_format.js`
needs to stub whichever surface ends up exposing the formatter.

---

### CRITICAL: `useImperial` must be a live getter, not a snapshot

**Spec lines:** §A L54 — "collect `useImperial` ... into an explicit
object so ruler.js consumes them as an interface."

`useImperial` at `frontend/app.js:122` is a **module-scope `var` inside
the app.js IIFE**. It cannot be exposed as a value-on-an-object
snapshot without losing the live-update semantics, because:

- The user toggles units via `input[name="units"]` radios at
  `app.js:1086-1103`. The handler at L1089-1090 mutates `useImperial`
  AND the global mirror `window._geographicaUseImperial`.
- The existing precedent for cross-IIFE live consumption is
  `navigation.js:197-201`:
  ```js
  // Reads window._geographicaUseImperial at call time so live changes
  // are observed
  function _geographicaUseImperial() {
    return typeof window !== 'undefined'
      && window._geographicaUseImperial !== false;
  }
  ```
  And `navigation.js:1032` exposes it as a function: `_useImperial:
  _geographicaUseImperial`. **It is called, not read.**

If the spec is implemented literally as
`window._appAPI = { useImperial: useImperial, ... }` snapshotted at init
time, then a user who toggles imperial→metric AFTER the page loads but
BEFORE drawing a measurement will see the ruler render in the OPPOSITE
unit system from the rest of the app. Worse, a user who toggles units
WHILE a measurement is finished will see all readouts (and the
sparkline stats grid) freeze at the pre-toggle units until the
measurement is cleared and redrawn.

**Recommended fix:** Spec §A explicitly require `_appAPI` be a
**live-getter object**:
```js
window._appAPI = {
  useImperial: function () { return useImperial; },          // getter
  haversineDistance: haversineDistance,                       // pure fn
  formatRouteDistance: formatRouteDistance,                   // pure fn
  formatDD: formatDD,                                         // pure fn
  // formatNavDistance handled per the prior CRITICAL finding
};
```

And §A explicitly state: "ruler.js MUST call
`window._appAPI.useImperial()` at every render — never destructure
into a local. Match the navigation.js:1032 precedent." Add a unit-flip
re-render trigger: ruler.js must subscribe to the
`input[name="units"]` change event (or a synthesized
`geographica:units-changed` CustomEvent that app.js dispatches)
and call `renderPanel(state)` on flip. Without this, the cached
`state.totalDistance_m` is fine, but the rendered string isn't.

§F edge-case row addition: "**User toggles imperial / metric after
Finish:** total / per-segment / sparkline-stats all re-render in new
units; data-shape unchanged."

---

### MAJOR: State-machine table doesn't handle "Measure tab is the active tab on page load"

**Spec lines:** §B L84-103.

The state-machine table starts assuming `idle` is already the entry
state when the user lands on the Measure tab. But: the existing
codebase **persists last-active sidebar tab to localStorage** (key
`sidebar-last-tab`, restored at `app.js:4105-4118`). If a user closed
the page with Measure as the active tab, the next page load fires the
restored-tab click handler synchronously **before** the user has had a
chance to interact with the map.

What's the entry state? The spec implies `idle`, which is correct.
But:

a. Does the floating mode banner show? (Spec L146 says banner is
   "visible during drawing/inserting" — so no.) Good — but verify.

b. Is `init()` called on every page load even if Measure tab isn't
   active? Spec §A L42 says "called once during bootstrap." So yes.
   Then the sources / layers are pre-emitted on map style.load
   regardless. Correct, just confirm.

c. Crucially: what happens when the user clicks Layers tab → comes
   back to Measure tab? Per spec L97 "Sidebar tab switched away with
   <2 vertices" → idle. But what about with **0 vertices**? Spec
   doesn't say, but logically it should also → idle / stay-idle. OK,
   this is implied.

d. Tab restored on page load with the prior session's measurement
   gone (since spec is ephemeral per non-goals): user sees an empty
   Measure panel. Spec § doesn't render this state. Need an "empty
   state placeholder" in §C — tested by `test_panel_render.js` row 1
   ("Empty state placeholder") so the test exists, but the spec's §C
   sections list 6 sections that all conditionally render and none
   describe the bare-empty-Measure-tab state's prompt copy.

**Recommended fix:**

1. §B add row: `idle | drawing | First map tap **fires only when the
   Measure tab is currently active** — taps on map while another tab is
   active don't append vertices. Empty-map taps in those tabs continue
   to fire the existing reverse-geocode handler at app.js:1622.`
2. §C add Section 0 (above Mode banner): "**Empty state placeholder.**
   When `vertices.length === 0` AND `status === idle`: render
   `<p class="ruler-empty-prompt">Tap the map to start measuring.</p>`
   inside `#measure-panel`. This is the affordance the user sees when
   they switch to Measure tab on a fresh page."
3. §B add explicit sentinel: "If the page loads with Measure as the
   restored active tab, ruler is in `idle` state with `vertices = []`
   regardless of any prior session — there is NO restoration."

---

### MAJOR: `isActive()` boundary leaves "tap empty map during editing" misclassified

**Spec lines:** §B L99 and L103.

The spec carefully lists `editing | editing | tap empty map → falls
through to existing reverse-geocode handler`. And §B L103 nails the
intent: `isActive()` returns true only for `drawing` + `inserting`,
false for `idle` + `editing`.


exec
/bin/bash -lc "sed -n '1,260p' dev/adversarial/2026-04-25-cost-methodology-r5-codex.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
2026-04-25T19:53:39.061475Z ERROR codex_core::codex: failed to load skill /home/administrator/Code/agent-skills/plugins/project-setup/skills/claude-agents-md-init/SKILL.md: invalid description: exceeds maximum length of 1024 characters
OpenAI Codex v0.118.0 (research preview)
--------
workdir: /home/administrator/Code/geographica
model: gpt-5.4
provider: openai
approval: never
sandbox: read-only
reasoning effort: none
reasoning summaries: none
session id: 019dc634-75e9-78e1-9f89-638739a7d60e
--------
user
You are conducting an independent adversarial review of Geographica's cost-audit methodology, from a non-Anthropic-family perspective. The goal is to catch issues that 4 parallel Claude Sonnet reviewers would systematically miss because they share Anthropic's mental model.

Your role is the cross-model sanity check.

## Read these files in /home/administrator/Code/geographica/

- scripts/audit_inference_cost.py
- tests/test_audit_inference_cost.py
- tests/fixtures/audit_inference_cost/*
- docs/superpowers/specs/2026-04-25-readme-overhaul-design.md (sections 4.2 through 4.3)

## Context

The script will produce the headline number for a README that gets pitched to senior decision-makers. Defensibility is the goal. Current verified output:

| Tier   | Turns  | Uncached I/O ($) | Full list price ($) |
|--------|-------:|-----------------:|--------------------:|
| Opus   | 36,536 |         2,221.61 |           19,556.73 |
| Sonnet |  8,548 |            23.72 |              184.55 |
| Haiku  |  9,386 |             5.70 |               74.46 |
| Total  |        |       2,251.04 |          19,815.75 |

Pricing constants used in the script:
- Opus 4.x:   $15/M input, $75/M output, cache 5m=$18.75/M (1.25x), cache 1h=$30/M (2x), cache read=$1.50/M (0.10x)
- Sonnet 4.x: $3/M input, $15/M output, same multipliers
- Haiku 4.5:  $1/M input, $5/M output, same multipliers

The methodology page will define the "headline" number as: uncached input + output for all tiers, summed. The "full list price" includes cache reads/writes at full Anthropic API rates.

## Your specific attack angles (different from what Anthropic models would think to attack)

1. **Pricing-source verification.** Independently look up Anthropic's documented per-token rates as of 2026-04 for Opus 4.x, Sonnet 4.x, and Haiku 4.5. Are the constants in the script correct? Are there model variants (e.g., "extended thinking", "1M context") with different rates that the script's substring matching ("opus" in model_id) would conflate?

2. **The transcript log format itself.** Anthropic's Claude Code stores per-turn usage in a JSONL transcript. Are there alternate transcript formats (older versions, fast-mode, batch-mode) that the script doesn't handle? Are there transcripts elsewhere on disk (like ~/.cache, ~/.local/share, or system-wide locations) that the script doesn't enumerate? An OpenAI-trained reviewer is more likely to ask "where else might billing data be stored" since OpenAI's tooling has different conventions.

3. **The "two numbers" framing.** From a non-Anthropic perspective, is the disclosure of $2,500 (uncached) AND $22,000 (full list) actually honest, or does it look like creative accounting? Compare to how OpenAI / GitHub Copilot / Cursor report their own usage. Is there a more standard/expected disclosure format?

4. **Subagent token counting.** The script enumerates parent transcripts (top-level *.jsonl) and subagent transcripts (*/subagents/*.jsonl). From a fresh perspective: is this the right boundary? Could subagent costs be already double-counted (e.g., reflected in a parent's "cache write" when the subagent's tool result returns)? Or under-counted (e.g., subagents that didn't get their own .jsonl because they failed mid-stream)?

5. **Anything else a Claude reviewer wouldn't think to check.**

## Output format

Write your findings as markdown. Structure:

# Codex R5 — independent cross-model review of cost methodology

**Reviewer model:** [whatever Codex model is running]
**Date:** 2026-04-25
**Scope:** independent verification + things 4 Sonnet rounds would systematically miss

## CRITICAL findings
## MAJOR findings
## MINOR findings
## Pricing-constant verification (with citations to Anthropic docs)
## Recommendation

Be direct and specific. Cite file:line in the script when relevant. If you find nothing of substance, say so plainly — the pattern "Codex catches what Claude misses" only matters when Codex actually catches something.

## Output destination

Save your full review to: dev/adversarial/2026-04-25-cost-methodology-r5-codex.md


codex
I’m treating this as a code-and-methodology review. The repo’s AGENTS routing points to a `review` skill, but that skill is not available in this session, so I’m doing the equivalent manually: read the audited code/tests/spec, verify Anthropic pricing against primary sources, then write the review content and note any write limitation if the sandbox blocks saving.
  → Read the audit script, tests, fixtures, and spec sections 4.2-4.3
  • Verify Anthropic pricing/constants and model-variant caveats from primary sources
  • Assess transcript enumeration, counting boundaries, and framing risks
  • Draft the markdown review and save it to dev/adversarial/...
exec
/bin/bash -lc "sed -n '1,260p' tests/test_audit_inference_cost.py" in /home/administrator/Code/geographica
 succeeded in 0ms:
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from audit_inference_cost import aggregate_directory, price_totals, PRICING

FIXTURES = Path(__file__).parent / "fixtures" / "audit_inference_cost"


def test_aggregate_single_opus_turn():
    totals = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl", subagent_glob="")
    assert totals["opus"]["input"] == 10
    assert totals["opus"]["cache_w_5m"] == 200
    assert totals["opus"]["cache_w_1h"] == 800
    assert totals["opus"]["cache_r"] == 5000
    assert totals["opus"]["output"] == 50
    assert totals["opus"]["turns"] == 1
    assert "sonnet" not in totals
    assert "haiku" not in totals


def test_empty_file_does_not_crash():
    totals = aggregate_directory(FIXTURES, parent_glob="empty.jsonl", subagent_glob="")
    # Empty file → no turns recorded but no exception
    assert totals == {} or all(t.get("turns", 0) == 0 for t in totals.values())


def test_subagent_transcripts_are_picked_up():
    """Subagent dir lives at <project>/<sessid>/subagents/*.jsonl.

    This test uses the DEFAULT subagent_glob (the flat */subagents/*.jsonl pattern
    that matches production behavior), not stem-correlated. The fixture
    abc123/subagents/sub_sonnet.jsonl is set up so the flat glob picks it up.
    """
    totals = aggregate_directory(FIXTURES, parent_glob="parent_with_subagent_ref.jsonl")
    # Parent contributed Opus
    assert totals["opus"]["turns"] >= 1
    # Subagent dir abc123/ contributed Sonnet + Haiku (picked up by flat glob)
    assert totals["sonnet"]["turns"] == 1
    assert totals["haiku"]["turns"] == 1


def test_price_totals_opus_known_values():
    totals = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl", subagent_glob="")
    priced = price_totals(totals)
    expected_full = (
        10 / 1e6 * 15
      + 200 / 1e6 * 15 * 1.25
      + 800 / 1e6 * 15 * 2.0
      + 5000 / 1e6 * 15 * 0.10
      + 50 / 1e6 * 75
    )
    assert abs(priced["opus"]["full"] - expected_full) < 1e-6
    expected_uncached = 10 / 1e6 * 15 + 50 / 1e6 * 75
    assert abs(priced["opus"]["uncached"] - expected_uncached) < 1e-6

exec
/bin/bash -lc "sed -n '1,260p' scripts/audit_inference_cost.py" in /home/administrator/Code/geographica
 succeeded in 0ms:
"""
Audit inference cost for a Claude Code project.

Reads ~/.claude/projects/<project-slug>/ (parent transcripts at top level,
subagent transcripts in <sessid>/subagents/) and prices each tier (Opus,
Sonnet, Haiku) at Anthropic's published per-token rates.

Reports two numbers:
  - "uncached" = input + output only (matches ccusage convention)
  - "full"     = above + cache writes (1.25x or 2x input) + cache reads (0.1x input)

Usage:
  python3 scripts/audit_inference_cost.py <project-dir>
  python3 scripts/audit_inference_cost.py ~/.claude/projects/-home-administrator-Code-geographica/
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

PRICING = {
    "opus":   {"input": 15.0, "output": 75.0},
    "sonnet": {"input":  3.0, "output": 15.0},
    "haiku":  {"input":  1.0, "output":  5.0},
}


def model_tier(model_id):
    if not model_id:
        return None
    m = model_id.lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return None


def aggregate_directory(directory, parent_glob="*.jsonl", subagent_glob="*/subagents/*.jsonl"):
    """Sum token counts across parent and subagent transcripts in a directory.

    parent_glob:    glob pattern (relative to directory) for parent transcripts
    subagent_glob:  glob pattern (relative to directory) for subagent transcripts;
                    pass empty string ("") to disable subagent scanning entirely
                    (useful for tests that want to scope to one parent file)
    """
    directory = Path(directory)
    files = sorted(directory.glob(parent_glob))
    if subagent_glob:
        files += sorted(directory.glob(subagent_glob))

    totals = defaultdict(lambda: defaultdict(int))
    for fp in files:
        try:
            with open(fp) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = obj.get("message")
                    if not isinstance(msg, dict):
                        continue
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    tier = model_tier(msg.get("model"))
                    if not tier:
                        continue
                    cc = usage.get("cache_creation") or {}
                    totals[tier]["input"]      += usage.get("input_tokens", 0) or 0
                    totals[tier]["cache_w_5m"] += cc.get("ephemeral_5m_input_tokens", 0) or 0
                    totals[tier]["cache_w_1h"] += cc.get("ephemeral_1h_input_tokens", 0) or 0
                    totals[tier]["cache_r"]    += usage.get("cache_read_input_tokens", 0) or 0
                    totals[tier]["output"]     += usage.get("output_tokens", 0) or 0
                    totals[tier]["turns"]      += 1
        except OSError:
            continue
    return {k: dict(v) for k, v in totals.items()}


def price_totals(totals):
    """Return per-tier {full, uncached} cost in USD."""
    priced = {}
    for tier, t in totals.items():
        p = PRICING[tier]
        full = (
            t.get("input", 0)      / 1e6 * p["input"]
          + t.get("cache_w_5m", 0) / 1e6 * p["input"] * 1.25
          + t.get("cache_w_1h", 0) / 1e6 * p["input"] * 2.0
          + t.get("cache_r", 0)    / 1e6 * p["input"] * 0.10
          + t.get("output", 0)     / 1e6 * p["output"]
        )
        uncached = (
            t.get("input", 0)  / 1e6 * p["input"]
          + t.get("output", 0) / 1e6 * p["output"]
        )
        priced[tier] = {"full": full, "uncached": uncached}
    return priced


def render_markdown(totals, priced):
    """Return a markdown table summarizing totals + prices."""
    lines = [
        "| Tier | Turns | Uncached I/O ($) | Full list price ($) |",
        "|------|------:|-----------------:|--------------------:|",
    ]
    grand_unc = grand_full = 0.0
    for tier in ("opus", "sonnet", "haiku"):
        if tier not in totals:
            continue

exec
/bin/bash -lc "sed -n '1,260p' dev/adversarial/2026-04-24-ruler-r5-codex.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
# Ruler spec v2 — adversarial review R5: Codex cross-validation
**Reviewer:** Codex (gpt-5.4)
**Date:** 2026-04-24
**Lens:** Cross-validation; integration risks; what R1-R4 missed

## Summary
v2 fixes most of the Sonnet-round ship blockers, especially the Terrarium decode, z=12 rationale, touch-target sizing, and the move away from stale `useImperial` capture. It still is not plan-ready: there is one remaining integration bug that will double-fire reverse geocode when selecting ruler vertices in `editing`, and several spec claims are still underspecified or too optimistic about rerender triggers, style-hook accounting, font fallback, edge-case guards, and test rigor.

The biggest pattern here is that v2 corrected the obvious broken formulas and missing handlers, but it still under-specifies the glue code. This is the final review round; the remaining defects are not cosmetic. They are the kinds of integration seams that ship as “mostly works” and then burn time in QA.

## Findings (CRITICAL / MAJOR / MINOR)

### CRITICAL

#### C1. Editing-state vertex clicks still leak into the generic reverse-geocode handler
Spec §B says `editing` vertex taps select the vertex while only empty-map taps should fall through to reverse geocode (spec lines 140, 150). But `_ruler.isActive()` is intentionally `false` in `editing`, so the proposed bail at the generic click handler is inactive precisely when vertex-selection clicks happen.

The real handler in `frontend/app.js:1622-1635` suppresses reverse geocode only when the click hits these layers:
- `imported-points`
- `imported-lines`
- `imported-polygons`
- `imported-polygon-outlines`
- `search-result-circles`

It does not include any future ruler layers. So in `editing`, a click on `ruler-vertex-hit-circles` will do both things:
- fire the ruler layer click/select path
- then fire the generic map click path and open the reverse-geocode popup

This is the missing fourth integration suppression path. It is not another existing external click handler; it is a missing exclusion in the generic handler’s own feature-hit test.

Required spec change:
- Add an explicit edit at the generic click handler so its `queryRenderedFeatures()` exclusion list includes the ruler hit/select layers, at minimum `ruler-vertex-hit-circles`, `ruler-vertex-circles`, and likely `ruler-line` if segment interactions are ever added.
- Or specify a stronger event contract: the ruler layer handler claims the click and the generic handler bails on `e.defaultPrevented` or an equivalent module-owned flag.
- Update the app.js integration inventory accordingly; this is a distinct integration edit, not covered by the three existing bail points.

Why this is ship-blocking: selecting a vertex is core editing behavior. If every select click also pops a reverse-geocode card, the edit model feels broken.

### MAJOR

#### M1. Unit-toggle rerender is still not specified as an actual mechanism
Spec §A correctly switches the source of truth to `window._geographicaUseImperial`, but then says updates propagate “on the next render tick” (spec lines 62-63). There is no such tick in the current app. The actual unit-radio handler in `frontend/app.js:1086-1100` updates the mirror, rebuilds the scale bar, and refreshes camera status; it does not notify ruler UI.

The navigation precedent in `frontend/navigation.js:204-208` is only a live-read helper. It solves stale reads, not DOM rerender.

As written, v2 leaves two incompatible interpretations:
- ruler rerenders only when some unrelated state change happens later
- ruler wires its own DOM listeners to the unit radios

Those are not equivalent, and the spec never chooses one.

Required spec change:
- Specify the rerender trigger explicitly.
- Best option: the existing unit handler dispatches `geographica:units-changed`, and ruler subscribes to rerender panel, banner text, and sparkline aria-labels without mutating data.
- If you want zero extra app.js coupling, say so explicitly and require `ruler.js` to subscribe directly to `input[name="units"]` changes during `init()`.
- Add an integration test that flips the real radio input and asserts that an already-rendered measurement changes units immediately, without extra map interaction.

R1/R4 caught the stale-source bug. v2 fixes the source, but not the rerender contract.

#### M2. The `addPlaceholderSources()` hook is real app.js work, but the insert-count accounting still omits it
Spec §D says style-load reattach must happen by extending `addPlaceholderSources()` so it calls `_ruler.reattachSources(map)` (spec line 209). That means `frontend/app.js` needs another edit inside the centralized source/layer bootstrap function at `frontend/app.js:295+`.

But the integration inventory in §A still claims “five inserts” plus one whitelist edit, and the coordination section repeats “five small inserts + one whitelist edit” (spec lines 88-95, 438-444). That is false. Even before R5’s new `editing`-state click fix, v2 already required another app.js modification for the style-load hook.

This matters because the spec is explicitly using insert counts to reason about merge-risk and implementation scope. If that accounting is wrong in the spec, the work decomposition is wrong too.

Required spec change:
- Count the `addPlaceholderSources()` hook as an app.js edit.
- Update the integration surface summary to reflect the real number of app.js touch points.
- Stop describing the app.js surface as “five inserts + one edit”; after R5 it is at least five inserts plus three edits, and more if you add an explicit unit-change event dispatch.

#### M3. The ruler label font stack is wrong relative to the actual style corpus
Spec §D requires `text-font: ['Metropolis Regular']` for `ruler-vertex-labels` and repeats that rule in the pitfalls checklist (spec lines 202, 430). That is not the prevailing style contract in the shipped tileserver styles.

Actual styles use a two-font fallback for normal labels:
- `tileserver/styles/positron/style.json:662` → `["Metropolis Regular", "Noto Sans Regular"]`
- `tileserver/styles/darkmatter/style.json:743` → `["Metropolis Regular", "Noto Sans Regular"]`
- `tileserver/styles/hybrid/style.local.json:1196-1198` → same two-font fallback

There is one single-font local-style exception for housenumbers in `tileserver/styles/positron/style.local.json:293-295`, but that is clearly not the general pattern for normal map text.

Required spec change:
- Change the ruler symbol layer to `text-font: ['Metropolis Regular', 'Noto Sans Regular']`.
- Update the checklist language to match the actual style-family convention instead of restating the wrong single-font rule.

This is not just aesthetic. The single-font stack is brittle for fallback glyph coverage.

#### M4. Terrarium decode is fixed, but no-data / impossible-value guards are still missing
The decode formula in §E.3 is now correct (spec lines 284-289). The spec still does nothing to prevent impossible pixels from poisoning the profile.

A raw Terrarium decode of `(0,0,0)` yields `-32768m`. If a tile edge, transparent pixel, corrupted read, or unexpected sentinel leaks through, that value will dominate min/max and likely gain/loss too. The spec currently says only “compute min/max/gain/loss on non-null samples” (spec line 312), but it never defines when a decoded sample becomes `null` for being impossible.

Required spec change:
- Define a decode guard.
- Minimum: if alpha is 0, return `null`.
- Also clamp decoded values outside a plausible DEM range, e.g. `< -500` or `> 9000`, to `null`.
- Add explicit tests for `(0,0,0)`, alpha-zero pixels, and out-of-range decoded heights.
- Update the edge-case table to say these become partial coverage, not absurd numeric extremes.

R2 hinted at this. v2 still ships without the guard.

#### M5. The test plan still misses the highest-value behavior-regression cases
The current test list covers geodesy, decode, state transitions, sparkline geometry, and basic keyboard handling (spec lines 366-381). It still misses several regressions that are likely in real implementation:

- LRU eviction is untested. There is no test that proves the cache actually evicts and stays bounded despite the spec mandating an LRU with a 30-tile cap.
- rAF drag coalescing is untested. The spec claims drag updates are coalesced by `requestAnimationFrame`, but there is no test proving repeated `mousemove`/`touchmove` events collapse to one `setData()` per frame.
- Multitouch cancel is untested. The edge-case table says `e.touches.length > 1` cancels drag, but there is no touch-specific test covering it.
- Unit rerender integration is untested. `test_unit_format.js` only validates the pure formatter, not the actual rerender path.
- The new R5 editing-click fix would be untested. The source-grep enforcement test currently only checks three bail regions. If the generic handler also needs ruler-layer exclusions, that enforcement must expand.

Required spec change:
- Add `test_tile_cache_lru.js`
- Add `test_drag_raf.js`
- Add `test_touch_multitouch_cancel.js`
- Add `test_units_rerender_integration.js`
- Expand the app.js enforcement test to verify the generic-click exclusion includes ruler layers or an equivalent claimed-click contract

#### M6. The manual ship-gate checklist still contains vague language that invites self-deceptive passes
The manual checklist is much better than v1, but several items are still too mushy to act as a release gate:
- “Gloved fingers ... vertex tap-target reachable”
- “HTTPS Tailscale + HTTP LAN: ruler works identically”
- “1000-mile path ... UI responsive”
- “Color contrast in sunlight ... clearly visible”
- “VoiceOver ... announced”

Those lines are not falsifiable as written. A tired reviewer can check them off after a casual glance.

Required spec change:
- Replace subjective wording with observable acceptance criteria.
- Example replacements:
- “Gloved fingers”: 8/10 first-attempt taps on a vertex must select without opening a reverse-geocode popup.
- “HTTP LAN vs HTTPS Tailscale”: same path, same units, same click flows, and elevation state transitions match; timing differences acceptable, missing UI states not acceptable.
- “1000-mile path”: banner, panel, and map remain interactive; explicit partial-profile notice appears.
- “VoiceOver”: row announces label + coordinates + selection state; sparkline announces min/max/gain/loss once; banner cancel button is focusable and named.

If this is the final adversarial round, the checklist should behave like a real ship gate, not a vibes list.

#### M7. The “KMZ-serializable” claim is broader than the data shape actually warrants
The spec claims the ruler state is “KMZ-serializable” both in the non-goals framing and the canonical state object heading (spec lines 35, 97). That is too broad.

What the shape actually supports is narrower:
- `vertices` can be exported to a minimal KML `LineString` coordinate list
- vertex labels can become names for point Placemarks if you choose to emit them
- computed metrics like `segments`, `coverageGaps`, `samplingState`, `samplingProgress`, and selection/edit-mode fields are not KML semantics

So yes, the geometry is exportable. No, the state shape is not a general “KMZ-serializable” object in any round-trippable sense.

Required spec change:
- Narrow the claim to: “The core geometry (`vertices`) is exportable to a minimal KML/KMZ LineString plus optional point Placemarks.”
- Do not imply that the whole runtime state object is the future persistence format.

This matters because broad future-proofing claims become architectural traps later.

### MINOR

#### N1. The spec still has no explicit English-only/i18n boundary
All user-facing strings, ARIA labels, unit abbreviations, decimal formatting, and hemisphere letters are English-only and hardcoded. That is consistent with today’s app, but the spec should say so instead of sounding locale-agnostic.

#### N2. Security posture is acceptable today only because ruler labels are internal
Current labels are generated as `V1`, `V2`, etc., so there is no immediate XSS surface. But the spec’s forward reference to persistence/export makes it likely that user-supplied names arrive later. Add one sentence now: ruler DOM rendering uses `textContent`, never `innerHTML`, for labels and stats. That matches the broader frontend posture in `app.js`, where imported HTML is explicitly sanitized with DOMPurify before insertion.

#### N3. Browser back-button behavior is not defined
The app does not currently use `history.pushState`, `replaceState`, `popstate`, or hash routing for sidebar tabs or measure state. That is fine. The spec should explicitly keep it that way for v1 so no one “improves” the feature by polluting browser history with draw/edit state.

#### N4. `test_terrain_rgb.js` keeps the wrong mental model alive
The test filename in §Testing still says `test_terrain_rgb.js` even though the whole point of R1/R2/R4 was that these are Terrarium tiles, not Mapbox Terrain-RGB. Rename it to `test_terrarium_decode.js` or `test_elevation_decode.js`.

## Cross-validation against R1-R4
R1-R4 did catch the major first-order failures, and v2 fixes most of them correctly.

- Terrarium decode: fixed correctly in §E.3. This was the biggest v1 math bug.
- z=12 resolution rationale: corrected correctly; the spec now states the real ~32 m/px figure and ties z=12 to actual data availability.
- `useImperial` source-of-truth: fixed partially. The stale-capture bug is gone because the spec now points at `window._geographicaUseImperial`, but the UI rerender trigger remains unspecified.
- Touch target sizing / touch thresholds / banner collision: substantially fixed. v2 is much more concrete than v1 on hit circles, touch thresholds, and banner behavior.
- Search/KMZ competing click handlers: fixed as far as `drawing`/`inserting` goes; the imported-layer and search-pin bails are now called out explicitly.
- `VALID_SIDEBAR_PANELS`: fixed correctly in the spec text.

What the Sonnet rounds did not fully close was the second-order integration logic:
- the generic click handler’s exclusion set in `editing`
- the actual unit-rerender mechanism
- the true app.js edit count once `addPlaceholderSources()` is included
- the font-stack mismatch between the spec and real style files

## What R1-R4 missed
The main fresh-eyes misses are not new algorithms. They are integration seams and too-broad-claim problems.

- Editing-state click leakage: R1-R4 focused on `drawing`/`inserting` suppression. They missed that `editing` also needs protection, but by a different mechanism because `_ruler.isActive()` is intentionally false there.
- Rerender vs live-read: they fixed the source-of-truth bug, but not the render-trigger bug.
- Style-hook accounting: they required `addPlaceholderSources()` but did not propagate that requirement into the app.js insertion-count and merge-risk accounting.
- Font fallback: they asserted Metropolis availability, but did not compare the ruler spec’s single-font stack against the actual two-font pattern in shipped style JSON.
- Terrarium guard rails: they corrected the formula but left the no-data/impossible-value path underspecified.
- Checklist rigor: they expanded the manual gate but still left several items subjective enough to self-pass.
- Future-proofing language: they accepted the “KMZ-serializable” phrase without narrowing it to what the state shape really supports.
- Secondary lenses: i18n boundary, future label-sanitization rule, and browser-history non-goal all remain implicit.

## Recommended spec changes
1. In §A “Minimal touch to existing files”, update the app.js inventory to include:
- one edit in `addPlaceholderSources()` for `_ruler.reattachSources(map)`
- one edit in the generic click handler’s feature-hit exclusion list for ruler layers in `editing`
- optionally one insert in the units handler if you choose explicit `geographica:units-changed` dispatch

2. In §B “State machine” around the `editing` row and `isActive()` contract, add:
- “Vertex-clicks in `editing` are claimed by ruler and MUST NOT reach reverse-geocode. The generic click handler excludes ruler layers from its `queryRenderedFeatures()` gate.”

3. In §A “Imperial/metric handling”, replace “next render tick” with a real contract:
- either `document.dispatchEvent(new CustomEvent('geographica:units-changed', ...))` from the existing units handler
- or direct radio-input subscriptions from `ruler.js`

4. In §D layer definition and pitfalls, change the font stack to:
- `text-font: ['Metropolis Regular', 'Noto Sans Regular']`

5. In §E.3 decode logic, add a guard:
- alpha-zero => `null`
- decoded values outside plausible DEM bounds => `null`
- impossible samples contribute to coverage gaps, not min/max

6. In §Testing, add tests for:
- LRU eviction
- rAF drag coalescing
- multitouch drag cancel
- unit-toggle rerender integration
- the fourth click-suppression path in `editing`

7. In the manual checklist, rewrite subjective lines as explicit pass/fail assertions.

8. In the non-goals / state-shape language, narrow “KMZ-serializable” to “geometry-exportable to minimal KML/KMZ”.

9. Rename `test_terrain_rgb.js` to something that does not reintroduce the already-fixed encoding confusion.

## Plan-readiness assessment
v2 should not ship as-is and should not be the implementation-plan baseline. It needs a v3 spec revision first.

The good news: the remaining issues are concentrated and fixable. The bad news: the top one is a core editing-path integration bug, and several others sit exactly where Geographica tends to regress later: glue code, style-hook accounting, and tests that validate abstractions but not the real event path. If this were implemented from v2 unchanged, expect at least one “tap vertex, popup opens too” bug and at least one “units changed but ruler text stayed stale until next interaction” bug.

exec
/bin/bash -lc "sed -n '1,260p' dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
---
round: 1
angle: TTM math and API correctness
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-20
agent: alder
---

# Round 1 — TTM math, API correctness, algorithmic edge cases

Eight findings against `docs/superpowers/specs/2026-04-20-nav-voice-ttm-design.md`. Focus: places where the algorithm as specified would fire the wrong number of prompts, at the wrong time, under specific but not-implausible inputs. Four MUST-FIX (F1.1, F1.2, F1.3, F1.4), three SHOULD-FIX, one NICE-TO-HAVE.

The single most severe bug is F1.1: `distanceToManeuver` in the current codebase returns a *signed* along-route difference. The spec assumes non-negative. Under GPS jitter, U-turn maneuvers with overlapping `begin/end_shape_index`, or a dead-reckoning extrapolation that walks past the next maneuver's begin-shape before `currentManeuverIdx` advances, `distToNext` goes negative → `ttm = negative / positive = negative` → `ttm <= 30` is trivially true → far-tier fires for a maneuver the driver has already executed or is in the middle of executing. This is exactly the "wrong prompt, wrong time" failure mode the spec is trying to eliminate.

---

### F1.1 — `distanceToManeuver` can return negative; negative TTM passes every threshold

**Severity:** MUST-FIX

**Claim in spec:** §4.3 computes `var ttm = distToNext / speed;` and then compares `ttm <= ttmPair[1]` / `ttm <= ttmPair[0]`. The spec treats `distToNext` as a non-negative "how far ahead is the next maneuver" value. §7 "Edge cases" does not contemplate negative distances.

**Reality:** In the current source (`frontend/navigation.js:209-214`), `distanceToCoordIndex` is defined as:

```js
function distanceToCoordIndex(segIndex, t, targetIndex) {
  if (!cumulativeDistances) return 0;
  var current = cumulativeDistances[segIndex] + segmentDistances[segIndex] * t;
  var target = cumulativeDistances[targetIndex];
  return target - current;   // unsigned subtraction — can be negative
}
```

`distanceToManeuver(snap, maneuverIdx)` at `navigation.js:309-313` wraps this without a `Math.max(0, …)` guard. It returns a negative number whenever the snap's along-route position exceeds the target maneuver's `begin_shape_index` position. Four realistic ways this happens:

1. **U-turn maneuvers.** Valhalla's `auto` costing sometimes emits a `begin_shape_index` for a U-turn maneuver that equals the **same** shape index as the previous maneuver's end. A snap that progresses by one shape index past the U-turn boundary — while `findManeuverForSegment` still reports the pre-U-turn maneuver — produces `targetIdx < segIdx`.
2. **Dead-reckoning overshoot.** `deadReckonTick()` at `navigation.js:686-700` calls `checkVoice(drSnap)` where `drSnap` is an extrapolated position. During a 30-second DR window at 15 m/s, the DR snap advances 450m. If the next maneuver is 300m away, the DR snap walks 150m past it — `distToNext < 0` — AND `currentManeuverIdx` may lag because `findManeuverForSegment` is called on the DR snap just before checkVoice. Under the spec's D1 suppression, a negative TTM makes the near-tier condition trivially true → near fires → `announcedSet[nearKey] = true` → real GPS returns → near already "announced" → driver never hears the turn they should have heard at the real 30s point.
3. **GPS jitter at a maneuver boundary.** Snap bounces between seg *N-1* and seg *N* across two ticks. If seg *N* is the first segment of the next maneuver, tick 1 sees `targetIdx > segIdx` (fine), tick 2 sees `targetIdx <= segIdx` (negative). Under the band-aid's 3-tier model this is masked by the distance-based check (400m threshold); under TTM, a negative TTM passes every threshold simultaneously.
4. **Route start at the first maneuver.** Valhalla's first maneuver has `begin_shape_index = 0`. If the snap starts at seg 0 with t > 0, then `current > target = 0` → `distToNext < 0`.

**Impact:** Depending on which of the four paths triggers, either (a) a prompt fires for an already-crossed maneuver (driver gets "Turn left onto Oak Ave" when they are already on Oak Ave — exactly the Villa Rita field symptom), or (b) a near-tier fires for the next-next maneuver prematurely, silently consuming `announcedSet[nearKey]` so the real near-tier never fires. Both are the class of failure this spec exists to prevent.

**Proposed fix:** Two changes, both in §4.3:

1. Clamp distance at the source. Before computing `ttm`:
   ```js
   var distToNext = Math.max(0, distanceToManeuver(snap, nextIdx));
   ```
2. Early-return when `distToNext === 0` AND `currentManeuverIdx` still reports the pre-maneuver index (a sentinel that the snap is at-or-past the boundary but state hasn't caught up):
   ```js
   if (distToNext === 0 && snap.segmentIndex >= m.begin_shape_index) return;
   ```

Additionally, §7 should add an edge case (E10?): "`distToNext` clamped to zero; when zero, near-tier fires only if `ttmPair[1] > 0` — which it always is — so the clamp is safe." §6.1 unit test matrix should add a cell where the snap's `segmentIndex === m.begin_shape_index && t > 0` to guard against regression.

**Sources:** `frontend/navigation.js:209-214` (`distanceToCoordIndex`), `frontend/navigation.js:309-313` (`distanceToManeuver`), `frontend/navigation.js:686-700` (`deadReckonTick`). Valhalla U-turn maneuver docs: https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/#maneuver-types (types 16/17 = uturn_right/left, shape-index semantics undocumented by Valhalla).

---

### F1.2 — Epsilon at threshold boundaries: `<=` vs `<` unspecified, floating-point comparison at integer seconds

**Severity:** MUST-FIX

**Claim in spec:** §4.3 uses `ttm <= ttmPair[1]` and `ttm <= ttmPair[0]` (inclusive). §5 invariants I1 and I2 assert "Exactly 2" / "Exactly 1" announcement counts. §6.1 asserts announcement count matches invariants across a matrix including the entry distance `{500, 80, 40, 10}` m and speeds `{30, 10, 3, 0}` m/s.

**Reality:** Floating-point division at matrix boundaries. Consider a unit test cell at `speed = 10 m/s, entry = 80m, costing = auto` (far_s = 30, near_s = 3, floor = 50):

- Simulated tick at dist = 300m: TTM = 300/10 = 30.0 exactly? **No.** Matrix simulates ticks at 1 Hz from entry. At tick 22, dist advances as `80 - 22*10 = -140`, so the approach actually ends around tick 8 at dist=0. But between tick 5 (dist=30) and tick 4 (dist=40), the 30m-equivalent far crossing happens at tick 5. TTM = 30/10 = **3.0** exactly. Far threshold 30s — dist is already 30m, so TTM = 3.0 < 30.0 — far fires.

Forget that test; consider the *actual* boundary case. A highway approach at `speed = 30 m/s` entering from `entry = 1000m`:

- Tick 1: dist = 1000, TTM = 1000/30 = **33.333…**. Not crossed.
- Tick 2: dist = 970, TTM = 32.333…. Not crossed.
- Tick 4: dist = 910, TTM = 30.333…. Not crossed.
- Tick 5: dist = 880 — but only if velocity is *exactly* 30 m/s. GPS speed is never exactly 30 m/s; it jitters around it. If `speedMedian()` returns 30.01 and dist is 900.0, TTM = 29.990… → **far fires**. If `speedMedian()` returns 29.99 and dist is 900.0, TTM = 30.011… → far does **not** fire. The single-sample difference between 29.99 and 30.01 — well within GPS noise — flips the announcement tick by one.

This is not directly a correctness bug *if* the invariants are "fires at or near the threshold." But I1/I2's claim of **"Exactly 2"** / **"Exactly 1"** announcements is tested against a simulator, and a deterministic simulator with integer-arithmetic speed (10.0 m/s exactly) will pass while a realistic noisy-speed simulator fails intermittently. The spec does not define simulator speed semantics — `simulateApproach({speed, entryDist, costing, steps})` in §6.1 is silent on whether `speed` is the deterministic tick-to-tick step or the mean of a noisy stream.

More critically: the `<=` operator with `MIN_SPEED_FLOOR = 1.0` produces one silent cliff. At `speedSamples = []` (empty) → `speedMedian()` returns 1.0 → `speed = max(1.0, 1.0) = 1.0` → `ttm = distToNext / 1.0 = distToNext` (as seconds numerically, but the units are bogus: distance-in-meters as time-in-seconds). When `distToNext = 30` exactly, `ttm = 30.0 <= 30.0` is **true** → far fires. When `distToNext = 30.00001`, it's false. This is not a bug; it's the designed fallback (§E2). But it means route-start at ≤ 30m auto triggers exactly one far-tier on the route-start tick. Combined with the ≤ 50m floor triggering near on the same tick (near wins, D1 suppresses far) — OK. But if entry is `30.5m`, neither TTM nor floor conditions fire on tick 1 (TTM = 30.5 > 30, dist = 30.5 < 50 → floor fires → near fires). Wait — 30.5 ≤ 50, so floor triggers near. So 1 prompt. Fine. But at `entry = 50.5m`, TTM = 50.5 > 30, dist = 50.5 > 50 — **nothing fires** on tick 1. User gets zero prompts until they move — but if they are stopped at a light, they never move, and `speedSamples` never populates → `speedMedian()` stays at `MIN_SPEED_FLOOR = 1.0` forever → TTM stays at 50.5 forever → **no prompt ever fires**. This violates G4 (prompt when stopped at turn).

**Impact:** G4 fails at `50m < distToNext ≤ (far_s × 1.0m/s) = 30m` gap — i.e., between 30m and 50m of distance with speed=0, the near-floor governs → fires; at exactly the floor (50m), fires; above the floor but below where far would fire if speed were realistic (80m city case: at 10 m/s, TTM = 8s, far would have already fired during the approach) — the user never stops here spontaneously. But the edge is real: if the driver starts navigation *while already stopped at a light 60m from a turn* (feasible in post-reroute or "start nav after already approaching" flows), they hear no prompt until they begin moving. That is arguably a bug since G4 explicitly guarantees "Near-tier prompt fires when the driver is stationary *at* the next maneuver" — and the design rationale in §4.3 point 2 asserts "at the floor distance (≤ 50m auto), near fires naturally." It does, but **only at distances ≤ 50m; between 50m and 60m at rest, nothing fires**, which a field tester would experience as "I started nav at the light, the turn is right there, why isn't the voice talking?"

**Proposed fix:** Three changes:

1. §4.3: explicitly document whether thresholds are `<=` (inclusive, current) or `<` (exclusive) and add a comment that the choice affects the count of ticks on which a threshold is "armed." Current `<=` is defensible; keep it.
2. §6.1: specify that `simulateApproach` uses deterministic integer-tick advancement (no noise) and document that noisy-stream behavior is covered by §6.2 outlier test. Or: add a §6.7 "Threshold-boundary jitter" test that injects ±0.5 m/s GPS noise over a 30-tick approach and asserts far-tier fires within a ±1-tick window of the noise-free baseline.
3. §7 (new E10): "Route-start at rest, 50m < dist ≤ (far_s × MIN_SPEED_FLOOR)m." Document the no-prompt case and either (a) accept it as a trivia-level bug, or (b) widen the floor to `far_s × MIN_SPEED_FLOOR = 30m` → that's narrower, not wider. Correct fix: set `VOICE_DISTANCE_FLOOR.auto = far_s × MIN_SPEED_FLOOR` = 30m × 1 = 30m? No — the floor is currently 50m, which is already wider than 30m. Check the arithmetic: `far = 30s, MIN_SPEED_FLOOR = 1.0m/s`, so at speed=1.0m/s, far fires at `ttm = 30s ≡ dist = 30m`. Floor is 50m (wider). So for `dist ∈ (50, ∞)` at speed=0, nothing fires — which is the bug. Fix: either (i) raise `MIN_SPEED_FLOOR` to make `far_s × MIN_SPEED_FLOOR ≥ VOICE_DISTANCE_FLOOR` — at 50m/30s = 1.67 m/s — which biases TTM unfavorably at low real speeds, or (ii) accept that the "at-rest" regime uses the floor and document that the floor (50m) is the "at-rest near-fire distance" with no at-rest far-tier.

**Sources:** §4.1 constants table, §4.3 algorithm, §5 invariants I1/I4, §6.1 test matrix.

---

### F1.3 — `speedSamples` never shifts back to empty, but **`applyReroute()` re-runs `tick()` with stale `lastSpeed` and EMPTY `speedSamples`**

**Severity:** MUST-FIX

**Claim in spec:** §4.2: "Integration into `reset()` and `applyReroute()`: both paths clear the sample window (`speedSamples = [];`)." §4.5 shows `applyReroute` ending with `if (lastGPS) tick(lastGPS);`.

**Reality:** Look at the sequence in §4.5's `applyReroute`:

1. `announcedSet = {};`
2. `speedSamples = [];`
3. `precomputeDistances();`
4. `state = "navigating";`
5. `if (lastGPS) tick(lastGPS);`

Step 5 immediately enters `tick()`, which calls `pushSpeedSample(gpsSpeed)` (§4.2 integration claim). At entry to `checkVoice()`, `speedSamples.length === 1` (the just-pushed sample). `speedMedian()` returns `sorted[0] = thatSingleSample`. If the driver was rerouted *because* GPS showed off-route (which is the triggering condition for most reroutes), the sample that caused the reroute may be anomalous — an outlier spike from stale Bluetooth pairing with a phone, a multipath echo, or the classic cold-start-GPS 50-m/s phantom velocity. The reroute-induced re-tick uses that single anomalous sample as the median.

Now compute: if the new route's first maneuver is 40m away and the single-sample speed is 50 m/s, TTM = 40/50 = **0.8s** < 3s near threshold → near fires → D1 suppresses far → driver hears ONE prompt at the moment of re-route. If the first maneuver is actually a quarter-mile away (400m away) with the reroute putting the user on a different road, TTM = 400/50 = **8s** < 30s far → far fires. Driver hears far-tier on a maneuver that, at realistic speed, is ~40 seconds away.

Meanwhile: the *very* scenario §G6 claims the design nails — "Reroute clears all voice state: `announcedSet` AND the speed-sample window. The new route's first prompt fires without suppression from prior state." — **is compromised by the reroute-tick's use of a single-sample warmup median**. The spec acknowledges this at §E1 ("at worst, one premature prompt per route") but the interaction with the post-reroute window is not documented: reroute typically happens during active driving where the driver is most cognitively loaded, and "one premature prompt" at that moment is the worst moment for it.

**Impact:** Post-reroute behavior is exactly the scenario this redesign is targeting (Villa Rita detour = rerouted 3-maneuver cluster). A single-sample warmup window that biases high under outlier speeds (per §4.2 comment) fires the far-tier too early on the new route. Combined with D1 suppression, this can either (a) make D1 fire for a maneuver that's far away and irrelevant, consuming the near-tier cache for that maneuver, or (b) fire a far-tier prematurely, contributing to the "too many prompts" regression the spec exists to fix.

**Proposed fix:** Three-layer defense:

1. §4.2: on `applyReroute`, **preserve the last N speed samples from the pre-reroute window** if they are within a plausibility band (e.g., 0.5× to 2× of `lastSpeed`). A driver who was going 10 m/s before the reroute is still going ~10 m/s after. Clearing to empty is unnecessary and harmful.
2. §4.3 (alternative): skip `checkVoice(snap)` entirely on the re-tick that `applyReroute` triggers. Add a `skipVoice` flag parameter to `tick()`. The re-tick's purpose is to push UI state and advance the snap; it does not need to fire voice prompts on the same frame as the reroute. The first *naturally-arriving* GPS tick after reroute (≤ 1 second later) will have `speedSamples.length === 1` still, but by tick 3 we're at full median. Delaying voice by 1-3 seconds post-reroute is operationally invisible.
3. §6.3 test: "Reroute state clearing" should explicitly assert that the re-tick does NOT fire `onVoiceCb` if the current fix is (2), OR that the retained speedSamples produce a sensible TTM if the fix is (1).

**Sources:** §4.5 `applyReroute` code block, §4.2 speed-smoothing section, §G6 invariant.

---

### F1.4 — D1 suppression can silently drop a legitimate far prompt in a short→long maneuver sequence with mid-cluster acceleration

**Severity:** MUST-FIX

**Claim in spec:** §4.3 lines 189-208 (the `if (nearWouldFire)` block): "on near-fire, also mark far as announced so it can never fire on a later tick. The driver hears exactly ONE prompt for this maneuver when they are already within near-tier at activation time." §5 I2 asserts "Exactly 1 announcement per maneuver when the driver's entry-point is already inside the near-tier condition."

**Reality:** D1 assumes that "near fires" implies "driver is actively executing this maneuver imminently." That's true for the maneuver the driver is *approaching*. But `announcedSet` is keyed on `nextIdx = currentManeuverIdx + 1` — the **single** maneuver ahead. Consider this sequence:

1. Driver approaches maneuver M (right turn), currently 40m away at 10 m/s.
2. `nearWouldFire` true (dist ≤ floor 50m). Near fires for M. `announcedSet['M-far'] = true`, `announcedSet['M-near'] = true`.
3. Driver executes M. `currentManeuverIdx` advances. New `nextIdx = M+1`.
4. Maneuver M+1 is 500m away (normal surface-street block). Driver accelerates to 30 m/s (merges onto arterial).
5. At speed 30 m/s, maneuver M+1's far-tier should fire at dist = 900m. Driver is at dist = 500m when they pick up speed. TTM = 500/30 = 16.7s — already past the 30s far threshold would have fired. **But** far-tier for M+1 has NOT been marked announced; `announcedSet[(M+1)-far]` is fresh. So far fires at a subsequent tick when TTM crosses 30 — which happens immediately (dist = 500, speed ≥ 16.7 m/s, TTM ≤ 30). **OK, no bug here.** Correction: my scenario doesn't trigger the bug.

Let me re-examine. The spec asks: "near-fire on a short-maneuver-then-long-maneuver sequence where the user's speed doubles mid-cluster." Consider:

1. Driver approaches M, 40m at 10 m/s. Near fires for M, D1 suppresses far for M. `currentManeuverIdx` incremented.
2. Maneuver M+1 is 30m PAST maneuver M (a close pair — e.g., "right onto X, then immediate right onto Y").
3. Driver is still 40m from M, which means driver is 70m from M+1. On the **same tick** that near fires for M, `checkVoice` examines only `nextIdx = M` — returns after firing M's near. M+1's far is not considered.
4. Next tick: driver moves to 30m from M. `currentManeuverIdx` is still M-1 (driver hasn't executed M yet). `nextIdx = M`. `announcedSet['M-near']` is true → `nearWouldFire` false. `announcedSet['M-far']` is true → `farWouldFire` false. Nothing fires. Driver passes M.
5. Driver executes M. `currentManeuverIdx = M`. `nextIdx = M+1`. Driver is now 30m from M+1 (it's a close pair). TTM = 30/10 = 3s = near threshold. Dist = 30m ≤ 50m floor. Near fires for M+1. Far suppressed. **Driver hears 2 prompts (one for M, one for M+1) in 30m of driving — fine.** Matches §6.4 Villa Rita scenario.

OK — still no bug. Let me try harder. The spec's attack prompt asks about "near-fire on a short-maneuver-then-long-maneuver sequence where the user's speed doubles mid-cluster." Consider:

1. Driver is at 2 m/s crawling in traffic, 60m from maneuver M. Near does NOT fire (dist = 60 > 50 floor, TTM = 30 > 3 near).
2. Far fires when TTM crosses 30: dist = 60, TTM = 30 — far fires. `announcedSet['M-far'] = true`.
3. Driver accelerates to 20 m/s (traffic clears). Now TTM = 60/20 = 3s at the moment the traffic clears — if dist is still ≈ 60 → TTM = 3 = near threshold. Near fires. D1 suppresses far (already announced, irrelevant). Same result as "single-prompt flow." 
4. **BUT:** this path fires two prompts (far at step 2, near at step 3) within a few seconds. I2's "exactly 1 when entering inside near-tier" does NOT apply here because the driver **entered from outside near-tier** — I1's "exactly 2 per maneuver" applies. Count: 2. Matches I1.

The bug I was hunting — "D1 silently drops a legitimate far prompt" — doesn't actually materialize in the core algorithm. The D1 consumption of farKey is tied to the *same* nextIdx whose nearKey fired. Subsequent maneuvers are separate keys, unaffected.

**However, a real D1 subtlety remains:** the distance-floor path. Consider:

1. Driver is at 40 m/s (highway), 300m from an off-ramp maneuver M.
2. TTM = 300/40 = 7.5s. Far threshold 30s — already past. Near threshold 3s — not yet. Dist = 300m — above floor 50m. Nothing fires.
3. Driver decelerates from 40 m/s to 10 m/s entering a congested exit zone. `speedMedian()` now returns 10. Dist = 150m (driver has moved). TTM = 15s — still past far's 30s threshold. Near: TTM 15s > 3s. Dist 150m > 50m. Nothing fires.
4. Driver decelerates to stop-and-go 1 m/s. TTM = 100m/1m/s = 100s. Nothing fires until dist ≤ 50m floor.
5. At dist = 50m, floor triggers near. D1 suppresses far. Driver hears **ONE prompt, 50m from the exit**, with no prior advance notice at highway speed.

This violates §G1 — "Exactly 2 voice prompts per maneuver when the driver enters from outside the far-tier threshold." The driver *did* enter from outside far-tier (at 300m highway, TTM = 7.5s was already inside far's 30s, so far should have fired). Wait — 7.5s < 30s means TTM IS inside far's threshold. Far should have fired on step 2. Let me recheck: TTM ≤ 30 means within far-tier. TTM = 7.5 ≤ 30 → TRUE → `farWouldFire` is TRUE. **Far fires at step 2.** Then steps 3-5 find far already announced; near fires at step 5.

OK, so on my highway example, far fires at dist=300m (giving ~7.5s advance notice at 40 m/s — the highway problem NG1 punts on but the math is correct). I1 is upheld.

So the actual finding is subtler: **D1 suppression is correct in the core case, but the spec's I2 prose conflates "driver enters inside near-tier" with "driver is close when the tick arrives." For the latter to be unambiguous, the spec must assert that `announcedSet` is cleared on maneuver index advance — which it implicitly is (keys are per-nextIdx), but this invariant is not called out.** If a reader re-implements D1 keyed on `currentManeuverIdx` (the maneuver the driver is ON, not the next one), D1 bleed-over between maneuvers becomes possible.

**Impact:** Low in the reference implementation as specified. But the spec's invariants I1/I2 are asserted as "by construction" — and the construction depends on the keying being `nextIdx`-scoped. A sloppy re-implementation that uses `currentManeuverIdx` as the D1 key (seemingly equivalent) would break I1 after the first near-fire.

**Proposed fix:** Reclassify from MUST-FIX to SHOULD-FIX in light of this re-examination; document explicitly:

1. §4.3 add a comment: "`announcedSet` keys use `nextIdx` (the upcoming maneuver), NOT `currentManeuverIdx` (the maneuver the driver is on). D1 suppression only affects the single upcoming maneuver and does not bleed across maneuver boundaries."
2. §5 I2: change "driver's entry-point is already inside the near-tier" to "nearKey for the upcoming maneuver fires before its farKey. D1 suppresses the farKey for that same maneuver only."
3. §6 test: add a cell that verifies far-tier for maneuver M+1 is NOT suppressed by a near-fire on maneuver M.

*Reclassifying to SHOULD-FIX after code re-inspection; retaining the finding because the ambiguity in I2's prose is real even if the reference implementation is correct.*

**Sources:** §4.3 algorithm, §5 I1/I2 invariants, §6.4 Villa Rita test.

---

### F1.5 — `speedMedian()` length-2 warmup bias is exploitable and the claim in §4.2 comment has an off-by-one

**Severity:** SHOULD-FIX

**Claim in spec:** §4.2 helper comment (lines 146-154):

```
// For length 3 (steady state): index 1 = true median.
// For length 1 (first tick): index 0 = only sample.
// For length 2 (warmup): index 1 = larger-of-two — biases slightly high during
// the single-tick warmup window; acceptable since TTM is dist/speed, so a
// biased-high speed yields a biased-low TTM (fires slightly early, not late).
```

**Reality:** The math is correct: `Math.floor(2/2) = 1` → `sorted[1]` = larger of two. But the stated acceptability claim ("fires slightly early, not late") does not hold uniformly:

1. **Speed-bias-high ≠ TTM-bias-low uniformly.** A high-biased speed decreases TTM. Smaller TTM makes threshold crossings **earlier in time** (in the spec's own words). But "earlier" is bad for a field-tester who's already complaining about too-many-prompts in the pre-remediation run. The band-aid commit `e63f6d9` that this spec replaces exists because prompts firing too early are the primary UX defect.

2. **The length-2 window persists for exactly 1 tick.** With 1 Hz GPS, that's 1 second. Under a noisy-GPS scenario (50 m/s spike at tick 2), the length-2 sample set is `[10, 50]` → sorted = `[10, 50]` → median = 50. TTM = dist/50 — a 5× underestimate of real TTM. If dist = 300m, TTM = 6s — well under far's 30s threshold. **Far fires 5× earlier than the no-outlier baseline would have fired.** The spec's §E1 acknowledges "at worst, one premature prompt per route" but this is a worst-case ~4.5× timing distortion, not a one-tick one.

3. **§I5 claim: "Once `speedSamples` is full (3 samples), median rejects any single outlier."** This holds for sample-3 rejecting sample-1 or sample-2 if the outlier is in the middle. But the `.shift()` policy in `pushSpeedSample` makes the window FIFO: outlier at position 0, then outlier at position 0 shifts to position-0 of a 2-element window? No — on the third push, the window becomes `[s1, s2, s3]`; on the fourth push, `[s2, s3, s4]`. So an outlier at `s1` is evicted by `s4`. Good. But an outlier at `s2` (the middle) lives in the window for 3 ticks total. Median rejects it at positions [s1, s2, s3] and [s2, s3, s4], but if `s3` is ALSO an outlier (common for correlated GPS glitches — multipath lasts multiple seconds), the window [s2, s3, s4] has median = s3 = outlier. I5's "single outlier per window" is the operative word — correlated double outliers defeat median-3.

**Impact:** One-second warmup windows that fire TTM thresholds 4-5× earlier than steady state. Correlated multi-tick GPS glitches (common in urban canyons, bridges, tunnels exiting, all classic navigation-pain environments) defeat the median-3 design. The spec's "1 premature per route" bound is understated.

**Proposed fix:**

1. §4.2: expand `SPEED_WINDOW_SIZE` from 3 to **5**. Median-of-5 rejects up to 2 correlated outliers. Cost: 2 extra ticks (2 seconds) to reach steady state. Acceptable; compared to the 2 seconds spent on the current warmup, the first 5 ticks are all "partial steadystate" anyway.
2. §4.2 change median algorithm to "median of samples with length ≥ 3; `MIN_SPEED_FLOOR` for length 0-2." This removes the length-2 larger-of-two bias entirely.
3. §4.2 (alternative, cheaper): explicitly cap single-tick pushSpeedSample inputs at `max(lastSpeed × 2.0, 5 m/s)` — a simple outlier-rejection band that prevents 50 m/s spikes from entering the window in the first place. `lastSpeed × 2.0` handles acceleration (doubling speed in 1 second is only possible in sports cars at ~0-60); `5 m/s` floor accommodates zero-to-moving transition.
4. §I5: reword to "A single-tick GPS speed outlier at a *non-central* position in the window does not cause a TTM threshold to fire…. Correlated multi-tick outliers are outside the design envelope and are mitigated by the band-cap in pushSpeedSample."

**Sources:** §4.2 `speedMedian()` helper, §5 I5 invariant, §E1 edge case.

---

### F1.6 — Valhalla verbal instruction fallback chain may produce `onVoiceCb("")`; downstream behavior is undefined

**Severity:** SHOULD-FIX

**Claim in spec:** §4.3 uses `text = m.verbal_pre_transition_instruction || m.instruction` for near-tier and `m.verbal_transition_alert_instruction || m.instruction` for far-tier. §E8: "Maneuver with empty `verbal_pre_transition_instruction` and empty `verbal_transition_alert_instruction`. Fallback to `m.instruction || ""`. Empty-string onVoiceCb: the near-tier logic still calls `onVoiceCb("")` because we did not add a guard — acceptable, the voice-picker / Web Speech API layer is robust to empty strings (preserves existing behavior from current code)."

**Reality:** The current code at `frontend/navigation.js:343-351` (the `announce()` helper that the spec deletes) has `if (muted || !text || !onVoiceCb) return false;` — the **`!text` guard is present in current code** and would reject empty strings. §4.3's proposed replacement inlines the muted check (`if (!muted && onVoiceCb) onVoiceCb(text);`) and DROPS the `!text` check. This is a regression, not a preservation of behavior. `onVoiceCb("")` is then invoked.

Downstream: `frontend/nav-ui.js:494-501`'s `onVoice(text)` — I'd need to re-read to confirm, but the composed voice-picker spec (2026-04-21) documents the callback forwarding `text` into `new SpeechSynthesisUtterance(text)`. Empty-string utterances:

- Chrome: `speechSynthesis.speak(new SpeechSynthesisUtterance(""))` silently completes (fires `start` then `end` with no audio).
- Safari: empty utterance fires `error` with `"synthesis-failed"` in some versions.
- Firefox: silently completes like Chrome.

Benign in Chrome, noisy in Safari (produces an error event that the voice-picker's `activePreviewUtterance` cleanup might handle, or might not — see voice-picker R1 F1.1).

More critically: Valhalla's verbal instruction fields are documented as **optional**. Per the Valhalla API reference (https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/#narrative), `verbal_pre_transition_instruction` and `verbal_transition_alert_instruction` are populated only when `directions_options.units` is set and the narration generator has text to emit. For certain maneuver types (`destination`, `start`, `merge` with no verbal narration), these fields are **absent from the JSON** — not just empty strings. `m.verbal_pre_transition_instruction || m.instruction` → if both are undefined, result is `undefined`. Then `if (afterIdx < …) text += ", then " + …` — **`undefined + ", then "` evaluates to `"undefined, then "`** (JavaScript string coercion of undefined).

**Impact:** On any maneuver where Valhalla omits both verbal fields AND the `m.instruction` is empty or undefined (rare but not impossible for arrival maneuvers), the voice speaks "undefined" (literally the string). This is the classic "the word undefined appears in a user-visible UI" bug.

**Proposed fix:** Three small changes:

1. §4.3: restore the `!text` guard in both near and far paths. Before `onVoiceCb(text)`, check `if (text && text.length > 0)`.
2. §4.3: defensively coerce `m.instruction` with `|| ""`: `var text = m.verbal_pre_transition_instruction || m.instruction || "";`.
3. §E8: revise to reflect that the `!text` guard IS present (after fix 1), and that an empty fallback means NO voice prompt fires, which is correct behavior — silence is better than "undefined" or an empty utterance triggering a Safari error event.

**Sources:** `frontend/navigation.js:343-351` current `announce()` with `!text` guard, Valhalla API narrative docs, §E8 spec.

---

### F1.7 — Dead-reckoning tick uses a stale speed median; DR's own extrapolation uses `lastSpeed` but voice uses `speedMedian()` — inconsistent

**Severity:** SHOULD-FIX

**Claim in spec:** §E7: "`deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap. `lastSpeed` from the last real GPS tick is used by DR's extrapolation but `speedMedian()` reads `speedSamples` — these do not update during DR. TTM during DR uses the last-real-median. Acceptable: GPS outage is rare and DR is short-lived (≤30s per `DEAD_RECKON_MAX`)."

**Reality:** Acceptability claim is the issue. DR extrapolates position using `lastSpeed` (a scalar). Voice TTM uses `speedMedian()` (a different scalar derived from the full samples window). These can diverge:

1. Driver GPS outage right after a deceleration. `lastSpeed = 2 m/s` (just before outage). `speedSamples = [10, 8, 2]` (the deceleration sequence). Median = 8.
2. DR extrapolates position at 2 m/s — correct for the "driver is stopping" scenario.
3. Voice TTM uses median = 8. TTM = drSnap.distToNext / 8. Far threshold 30s → dist = 240m. Near threshold 3s → dist = 24m.
4. DR position advances 2 m/s × 30s = 60m over the outage. At the start of outage, dist was 300m → at end, dist = 240m. TTM (using median 8) = 240/8 = 30s. Far fires at the end of the outage based on a speed the driver is no longer at.

exec
/bin/bash -lc "sed -n '1,260p' dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
---
round: 6
angle: Codex cross-validation
reviewer: codex v0.118.0
date: 2026-04-20
agent: alder
---

# Round 6 — Codex cross-validation

## MUST-FIX

### F6.1 — The spec’s route-start guarantees do not hold on this engine’s actual `start()` path

**Severity:** MUST-FIX

**Quoted spec claim:** “**G2.** Exactly 1 voice prompt per maneuver when the driver enters already inside the near-tier condition” and “**G4.** Near-tier prompt fires when the driver is stationary *at* the next maneuver.”

**Reality / impact:** The live engine does not run the TTM pipeline on `start()`. In [frontend/navigation.js](/home/administrator/Code/geographica/frontend/navigation.js:758), `start()` snaps, stores `lastGPS`, sets `state`, and immediately `emitUpdate(buildState(...))`, but it does **not**:
- set `currentManeuverIdx` from the snap,
- seed `speedSamples`,
- call `checkVoice(snap)`.

That means the spec’s route-start and “already inside near-tier” scenarios are not true on the codepath users actually hit when starting navigation on-route. If the user starts 20-40m before a turn, they get no prompt on activation. If GPS then keeps reporting the same lat/lon, [updateGPS](/home/administrator/Code/geographica/frontend/navigation.js:802) dedups unchanged positions and still does not call `tick()`, so the prompt can remain suppressed until the vehicle moves.

There is a second-order correctness issue too: `buildState()` reads `currentManeuverIdx`, but `start()` leaves it at the reset default `0`, so a mid-route start can render the wrong `nextManeuver` until the first movement tick.

**Proposed fix:** The spec needs an explicit startup-initialization step, not just a `tick()` rewrite. On the on-route branch of `start()`:
- set `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`,
- seed the speed window from `savedGPS.speed`,
- decide whether `checkVoice(snap)` is allowed on start or explicitly deferred.

If immediate start-time voice is desired, say so and update `nav-ui.js` assumptions too. If not, narrow G2/G4 so they apply only after the first post-start GPS tick.

---

### F6.2 — “No nav-ui changes” becomes false if start-time voice is allowed

**Severity:** MUST-FIX

**Quoted spec claim:** “**NG3.** Changes to `frontend/nav-ui.js`’s voice pipeline. The engine-side `onVoiceCb(text)` contract is preserved exactly” and “**G9.** Mute-state interaction unchanged.”

**Reality / impact:** The current UI wiring assumes `nav.start()` is voice-silent. In [frontend/nav-ui.js](/home/administrator/Code/geographica/frontend/nav-ui.js:154), the order is:

1. `nav.onVoice(onVoice)`
2. `nav.start(routeData)`
3. `nav.setMuted(muted)`
4. `WakeLock.acquire()`
5. `primeSpeech()`

If the TTM spec is implemented literally enough to satisfy G2/G4 on start, the first prompt can fire **before** mute sync and **before** speech priming. That creates two regressions the spec currently says do not exist:

- A muted user can still hear the first prompt, because engine `muted` defaults false until [line 161](/home/administrator/Code/geographica/frontend/nav-ui.js:161).
- The first utterance can happen before the UI’s speech warm-up path, which the file explicitly treats as ordering-sensitive.

This is not theoretical; it is a direct consequence of fixing F6.1 without updating the UI contract.

**Proposed fix:** The spec must choose one of these and say so explicitly:
- Keep `start()` voice-silent and scope G2/G4 to post-start GPS ticks only.
- Or allow start-time voice, but then `nav-ui.js` is in scope: move `nav.setMuted(muted)` before `nav.start(routeData)`, and re-evaluate whether `primeSpeech()` / wake-lock ordering must move too.

Right now the spec promises both “route-start prompt works” and “no nav-ui changes,” but this codebase cannot satisfy both simultaneously.

---

### F6.3 — The synthetic “3-maneuver cluster → 3 prompts” test is off by one against actual engine maneuver semantics

**Severity:** MUST-FIX

**Quoted spec claim:** “**§6.4 Dense-cluster (Villa Rita synthetic) test:** Synthesize a **3-maneuver route** with maneuvers spaced 30m apart… Assert exactly **3 voice prompts** fired.”

**Reality / impact:** This engine voices the **upcoming** maneuver at `nextIdx = currentManeuverIdx + 1`; it does not voice the maneuver you are already on. The existing fixture in [frontend/tests/engine/test_runner.mjs](/home/administrator/Code/geographica/frontend/tests/engine/test_runner.mjs:48) shows the convention clearly: a “3-maneuver route” is actually “2 turns + arrival,” and the first spoken turn is maneuver index `1`, not `0`.

So a literal “3 maneuvers total” synthetic route cannot produce “3 spoken maneuver prompts” under current semantics unless you also change initialization semantics. With the current engine model, a “3 prompts in a close cluster” scenario needs either:
- 4 maneuvers total (lead/current + 3 upcoming spoken maneuvers), or
- an explicit change in how `currentManeuverIdx` is initialized for synthetic tests.

If this is left ambiguous, an implementer can write a passing synthetic that does not correspond to live engine behavior, or a failing one that appears to disprove the spec even though the geometry is wrong.

**Proposed fix:** Rewrite §6.4 in engine-native terms:
- either “3 **upcoming spoken maneuvers** after the current leg,”
- or “4 maneuvers total, yielding 3 spoken prompts.”

Also specify whether arrival is part of the count. The current wording mixes product-language “maneuver count” with engine-language “next maneuver index” and will mislead test authors.

---

### F6.4 — G7 overclaims determinism; this engine still depends on wall-clock scheduling, not just route + GPS values

**Severity:** MUST-FIX

**Quoted spec claim:** “**G7.** Behavior is deterministic: identical `(route, GPS stream)` inputs produce identical announcement counts and timing. No hidden cooldown or randomness.”

**Reality / impact:** In this codebase, voice timing is not determined solely by route shape and GPS sample values. It also depends on real clock behavior:

- `tick()` uses `Date.now()` repeatedly in [frontend/navigation.js](/home/administrator/Code/geographica/frontend/navigation.js:549).
- stale-GPS voice can be generated by the 1 Hz interval in [startStaleChecker()](/home/administrator/Code/geographica/frontend/navigation.js:706).
- `updateGPS()` ignores the incoming `gpsData.timestamp` field and stamps `lastGPSTime = Date.now()` itself at [line 816](/home/administrator/Code/geographica/frontend/navigation.js:816).

So the same coordinate/speed sequence delivered with different inter-arrival timing can produce different results:
- one run may enter dead reckoning and fire voice,
- another may not,
- reroute timeout behavior also changes with wall-clock delay, not just sample content.

That does not make the design invalid, but the invariant as written is false for the real engine.

**Proposed fix:** Narrow G7 to something the implementation can actually guarantee, for example:
- “Deterministic for identical route, GPS samples, and timer schedule,” or
- “Deterministic on the direct `tick()` path; stale-GPS / DR paths remain clock-dependent.”

Also make the test plan reflect that scope. Otherwise the spec is promising a property the engine architecture does not have.

---

## SHOULD-FIX

### F6.5 — Prompt counts in the spec are callback counts, not necessarily user-heard prompts

**Severity:** SHOULD-FIX

**Quoted spec claim:** “Villa Rita post-reroute 3-maneuver cluster: **3 prompts total**” and “Pass: **≤ 3 prompts** for the rerouted 3-maneuver cluster.”

**Reality / impact:** In the actual UI, each voice event cancels whatever is currently speaking before starting the new utterance. See [frontend/nav-ui.js](/home/administrator/Code/geographica/frontend/nav-ui.js:494):

```js
speechSynthesis.cancel();
speechSynthesis.speak(utterance);
```

That means the spec’s prompt counts are counts of `onVoiceCb` invocations, not necessarily counts of complete audible prompts. In a dense cluster, “3 callbacks” can still sound like “the first phrase got chopped off, then another one interrupted it.” That is a materially different user outcome from the safety claim the spec is making.

Rounds 1–5 focused on when the engine fires. The missing cross-validation point is that the UI currently treats prompts as preemptive, not queued.

**Proposed fix:** In §6.5, define the field gate in audible terms, not just callback-count terms. At minimum capture:
- callback count,
- whether any prompt was canceled by a later one,
- subjective audibility/intelligibility.

If you want to keep NG5 as-is, then at least state explicitly that the “3 prompts” headline means “3 engine callbacks,” not “3 fully spoken utterances.”

---

### F6.6 — Mid-route start correctness needs to be named as a precondition or tested explicitly

**Severity:** SHOULD-FIX

**Quoted spec claim:** “TTM is a pure in-engine change. External contract surfaces are unchanged.”

**Reality / impact:** The spec repeatedly reasons about “route-start into a close maneuver” and “post-reroute into a close maneuver,” but this engine also supports starting while already on-route or partway through a route. On that path, [start()](/home/administrator/Code/geographica/frontend/navigation.js:758) currently emits UI state without reconciling `currentManeuverIdx` to the snap. That is not just a voice issue; it is a general navigation-state issue, and TTM makes it more visible because voice timing now depends on a correctly identified “next maneuver.”

If the spec is intentionally not fixing mid-route start semantics, it needs to say that. Otherwise implementers will assume the existing startup behavior is already valid and only patch `checkVoice()`.

**Proposed fix:** Add one explicit statement to the spec:
- either “TTM assumes `start()` is corrected to initialize maneuver state from the snap,”
- or “mid-route start remains out of scope; TTM correctness is guaranteed only after the first movement tick.”

A single engine test for “start while already snapped after maneuver 0” would close this gap cleanly.

---

codex
I’ve got the draft and the sampled review artifacts. Next I’m checking two things in parallel: whether the exclusivity labels survive direct text comparison, and whether the external cost-rubric citations actually support the specific multipliers being claimed.
web search: 
web search: NIST SP 500-235 defect cost production 30x software testing PDF
web search: 
web search: '30' in https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf
web search: 
web search: NIST economic impacts of inadequate infrastructure for software testing pdf 2002 defects cost phase
web search: 
web search: https://samate.nist.gov/docs/econImpactSumm.v23.pdf
web search: 
web search: IEEE article Steve McConnell classic mistake 100x defect cost myth
exec
/bin/bash -lc "rg -n \"reverse-geocode|queryRenderedFeatures|editing state|editing\\)|ruler layers|font stack|Metropolis Regular|Noto Sans Regular|sentinel|0,0,0|Terrarium\" dev/adversarial/2026-04-24-ruler-r*.md" in /home/administrator/Code/geographica
 exited 127 in 0ms:
/bin/bash: line 1: rg: command not found

exec
/bin/bash -lc "rg -n \"distanceToManeuver|negative TTM|start\\(\\)|checkVoice\\(|currentManeuverIdx|no nav-ui changes|G7|deterministic|3 prompts\" dev/adversarial/2026-04-20-nav-voice-ttm-r*.md" in /home/administrator/Code/geographica
 exited 127 in 0ms:
/bin/bash: line 1: rg: command not found

exec
/bin/bash -lc "rg -n \"pricing constants|Opus 4|\\"'$15/'"\\"'$75|5'"\\.6x|double-count|streaming partial|message\\.id|cache-write exclusion|ccusage|cache reads|reproducibility\" dev/adversarial/2026-04-25-cost-methodology-r*.md" in /home/administrator/Code/geographica
 exited 127 in 0ms:
/bin/bash: line 1: rg: command not found

codex
`rg` is unavailable in this environment, so I’m falling back to `grep` for cross-file comparison. I’m specifically checking whether the “exclusive” findings were actually absent, or just phrased differently in the peer review files.
exec
/bin/bash -lc 'grep -RInE "reverse-geocode|queryRenderedFeatures|editing state|ruler layers|Metropolis Regular|Noto Sans Regular|sentinel|0,0,0|Terrarium" dev/adversarial/2026-04-24-ruler-r*.md' in /home/administrator/Code/geographica
 succeeded in 0ms:
dev/adversarial/2026-04-24-ruler-r1-architectural.md:16:   project's elevation tiles are **Terrarium encoding**. Decoded
dev/adversarial/2026-04-24-ruler-r1-architectural.md:47:But the project's elevation tiles are **Terrarium-encoded** (Mapzen / AWS
dev/adversarial/2026-04-24-ruler-r1-architectural.md:53:  says "Terrarium encoding"
dev/adversarial/2026-04-24-ruler-r1-architectural.md:62:| Terrarium | `(R*256 + G + B/256) - 32768` | 0 m |
dev/adversarial/2026-04-24-ruler-r1-architectural.md:240:   to fire the existing reverse-geocode handler at app.js:1622.`
dev/adversarial/2026-04-24-ruler-r1-architectural.md:246:3. §B add explicit sentinel: "If the page loads with Measure as the
dev/adversarial/2026-04-24-ruler-r1-architectural.md:257:through to existing reverse-geocode handler`. And §B L103 nails the
dev/adversarial/2026-04-24-ruler-r1-architectural.md:265:measurement. The reverse-geocode popup at `app.js:1622` showing up
dev/adversarial/2026-04-24-ruler-r1-architectural.md:277:  false for `idle` and `editing` — the user CAN use reverse-geocode
dev/adversarial/2026-04-24-ruler-r1-architectural.md:279:  reverse-geocode behind editing because (a) the editing UI is
dev/adversarial/2026-04-24-ruler-r1-architectural.md:311:   ruler layers may end up below imagery layers (wrong — spec L128
dev/adversarial/2026-04-24-ruler-r1-architectural.md:451:row's Style cell: `'text-font': ['Metropolis Regular', 'Noto Sans Regular']`
dev/adversarial/2026-04-24-ruler-r1-architectural.md:457:serves `Metropolis Regular` from `tileserver/fonts-served/Metropolis Regular/`.
dev/adversarial/2026-04-24-ruler-r1-architectural.md:703:| 8 | Symbol-layer glyphs reliability | Yes — see MAJOR finding above | Resolved: works as long as `text-font` array is `['Metropolis Regular', 'Noto Sans Regular']` to match the project's served fonts at `tileserver/fonts-served/`. |
dev/adversarial/2026-04-24-ruler-r1-architectural.md:709:1. **§E.3 L181-184** — replace Mapbox decode with Terrarium decode (CRITICAL #1).
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:12:Two **CRITICAL** issues, six **MAJOR** issues, three **MINOR** issues. The spec's biggest problem is that **its elevation-decode formula is for the wrong encoding**: the existing pipeline ships AWS Terrarium-encoded tiles (verified: `frontend/app.js:325, 334` use `encoding: 'terrarium'`; `scripts/download_elevation.py:39` pulls `s3.amazonaws.com/elevation-tiles-prod/terrarium/`; mbtiles metadata `name=elevation_terrarium`), but spec §E.3 codes Mapbox Terrain-RGB. Every elevation reading would be off by ~10000 m and a wrong slope. The second critical issue is that the spec's "~9.5 m/px at AZ latitude" claim for z=12 is **mathematically wrong** — the actual figure is ~32 m/px, off by 3.4×. This in turn invalidates the 50-tile cap, the 200-sample logic, and the entire "Why z=12" justification.
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:18:### F2.1 — CRITICAL — Wrong elevation decode formula (Mapbox Terrain-RGB vs AWS Terrarium)
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:35:- mbtiles file at `/srv/geographica/data/elevation.mbtiles` (127 GB, z=0..14, 1.47M tiles): metadata `description = "Terrain-RGB elevation tiles (Terrarium encoding)"` (note the misleading description string — the format **name** is Terrarium, the description text accidentally hybridizes both names).
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:37:The correct AWS Terrarium decode is:
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:47:- Terrarium formula: `(129*256 + 232 + 128/256) - 32768 = (33024 + 232 + 0.5) - 32768 = 488.5 m` (matches Phoenix elevation of ~340-500 m).
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:51:**Recommendation:** Rewrite §E.3's `elevationFromRGB` to the Terrarium formula. Add a unit-test fixture pinned to a real `(R, G, B)` triple from the existing mbtiles whose decoded elevation matches a known ground point (USGS DEM cross-check). Add a sanity-clamp: `if (elev < -500 || elev > 9000) return null` — Terrarium's encoding accommodates -32768..+32767, but real DEM values outside CONUS bounds [-100, 4500] should be treated as "decode failure / NoData sentinel" defensively.
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:53:The pitfalls doc should add an entry about Terrarium-vs-Terrain-RGB confusion — it's a recurring foot-gun (the description string in our own mbtiles uses "Terrain-RGB" as a generic phrase, which is what likely confused the spec author).
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:124:- Specify exactly what's cached: a `Map<key, Uint8Array>` of `(tx, ty) → Uint8Array(196608)` (RGB-only; the spec already only decodes RGB and we don't need alpha for a Terrarium decode). 192 KB/tile, no `Image`/`ImageBitmap` retained.
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:278:(b) **Vertex pixel at exact tile boundary** (e.g., sample lat/lng maps to pixel at intra-tile y=255 or y=0). Because Terrarium tiles don't include 1-px overlap, a sample at the boundary may decode from the wrong tile due to floating-point rounding (`Math.floor((lat - tileTop)/pixelHeight)` can give 256 or -1 for boundary cases). Result: array out-of-bounds → undefined → null sample → unnecessary coverage gap.
dev/adversarial/2026-04-24-ruler-r2-scale-performance.md:326:1. **CRITICAL:** Rewrite §E.3 `elevationFromRGB` to AWS Terrarium decode `(r * 256 + g + b/256) - 32768`. Add fixture-based unit test pinned to a known mbtiles tile.
dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:38:- Either a separate, invisible-but-pickable transparent circle layer with `circle-radius: 22` (44 px) and `circle-color: rgba(0,0,0,0)` or with low opacity, sitting above `ruler-vertex-circles`, OR
dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:39:- A hit-test step in the touchstart handler that tolerates the nearest vertex within ~22 px regardless of MapLibre's `queryRenderedFeatures` result.
dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:43:**Recommended fix:** Add `ruler-vertex-hit-circles` layer at `circle-radius: 22, circle-color: rgba(0,0,0,0.001)` (just non-zero so MapLibre's hit-test counts it). All `mousedown`/`touchstart` listeners hit-test against this layer; only the visual radii stay at 8/11.
dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:59:4. **Synthetic mouse events on iOS Safari** fire ~300ms after `touchend` if and only if the touch sequence was a "click candidate" — short, small motion. Even with `preventDefault()` on touchstart, if MapLibre re-emits a click via `map.on('click')`, that handler will fire. This is exactly the path that triggers the reverse-geocode popup at app.js:1622. The `isActive()` mode-flag suppression must cover the synthetic click after a tap-on-vertex too — the spec only suppresses for `drawing`/`inserting`, but the *editing* state's tap-on-vertex must also not bubble up to reverse-geocode. The spec text in §B says "tap empty map → falls through to existing reverse-geocode handler" — but the handler at 1622 doesn't currently distinguish "tap on vertex" from "tap on empty map" because MapLibre `click` events fire regardless of which feature is under the cursor unless the inner handler checks `queryRenderedFeatures`.
dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:67:- Existing reverse-geocode handler at app.js:1622 must also early-return when the click feature-list contains `ruler-vertex-circles` or `ruler-vertex-hit-circles`. Today the handler only checks 5 layer names; ruler layers must be added.
dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:322:2. **§D new subsection D.5 "iOS Safari touch contract":** Specify use of MapLibre's normalized event API; document `passive: false`; add `touch-action: manipulation`; require reverse-geocode handler at app.js:1622 to skip when ruler vertex layers are under cursor; document PWA standalone-mode behavior or explicitly defer.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:14:  - **C1:** Spec's `elevationFromRGB` decode formula is for **Mapbox Terrain-RGB**, but the existing tiles are **Terrarium-encoded** (verified: `app.js:325` `encoding: 'terrarium'`; `download_elevation.py:39` source URL). Every elevation readout would be off by ~10000m baseline + scale factor. Sparkline numbers would be nonsense.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:20:The edge case table at §F has 14 entries; this review surfaces ~25 additional cases the spec misses, several of which produce silent wrong-output rather than visible errors. The §"Testing strategy" section names 6 unit + 3 integration tests but leaves three high-value paths uncovered: the elevation-decode contract under Terrarium, the `_appAPI` cross-tab unit-toggle propagation, and the layer-stacking interaction with KMZ pin click handlers.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:40:This is the **Mapbox Terrain-RGB** decoder. But the actual tiles in `/srv/geographica/data/elevation.mbtiles` are **Terrarium-encoded** (Mapzen / Terrain Tiles AWS Open Data format). Two independent confirmations:
dev/adversarial/2026-04-24-ruler-r4-robustness.md:45:The Terrarium decode is:
dev/adversarial/2026-04-24-ruler-r4-robustness.md:53:- Terrarium-correct: ~1500m
dev/adversarial/2026-04-24-ruler-r4-robustness.md:61:1. Replace the decode formula with the Terrarium variant.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:62:2. Add `test_terrain_decode.js` (rename from `test_terrain_rgb.js`) that asserts `elevationFromRGB(0, 128, 0) === -32512` (sentinel low), `elevationFromRGB(128, 0, 0) === 0` (sea level), and `elevationFromRGB(135, 79, 192) === 1871.75` (an actual CONUS-mountain pixel — pick a real one from a downloaded tile and freeze it).
dev/adversarial/2026-04-24-ruler-r4-robustness.md:63:3. Add a comment in ruler.js linking to `app.js:325` so future maintainers see the contract: "elevation tiles are Terrarium per the source declaration; if `encoding:` ever changes, update this decoder in lockstep."
dev/adversarial/2026-04-24-ruler-r4-robustness.md:64:4. Cross-reference in implementation-pitfalls.md: add "§16 Terrain-RGB vs Terrarium are not interchangeable; Geographica uses Terrarium."
dev/adversarial/2026-04-24-ruler-r4-robustness.md:117:- `app.js:1622` — generic `map.on('click', ...)` for reverse-geocode popup.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:119:In MapLibre, layer-specific handlers fire *in addition to* the generic handler when a feature is at the click point — the generic handler suppresses itself via `queryRenderedFeatures` (L1628-1632), but the layer-specific handlers run unconditionally.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:276:Per C1, the tile encoding is Terrarium not Terrain-RGB. File should be `test_terrain_decode.js` or `terrain-decode.test.mjs` to match the actual data format.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:317:| E11 | User taps the floating mode banner's `[×]` while `inserting` AND a vertex is mid-tap | Race: banner click registers, state goes to `editing`, then map tap arrives, no longer in `inserting` so map tap falls to default reverse-geocode | Spec needs: "during the 200ms tap-vs-drag window, banner taps are blocked." |
dev/adversarial/2026-04-24-ruler-r4-robustness.md:340:| z=12 sample zoom universally appropriate? | OQ2 | YES for CONUS Terrarium. Add explicit assertion in test that elevation MBTiles `maxzoom >= 12` (already declared `maxzoom: 14` in app.js:324). Future "z=12 unavailable" → fall back to `min(12, source maxzoom)`. |
dev/adversarial/2026-04-24-ruler-r4-robustness.md:354:1. **Replace `elevationFromRGB` with Terrarium decoder** (C1). Verify against a real downloaded tile. Add `pngjs`-based regression test.
dev/adversarial/2026-04-24-ruler-r4-robustness.md:403:**Recommendation to controller:** spec is *almost* plan-ready, but C1 and C2 are concrete, codebase-grounded ship-blockers — both would survive plan-writing and bite during implementation. The plan author needs the Terrarium decoder spelled out and the `useImperial` propagation mechanism nailed down before they can write task descriptions. The 8 MAJOR items are tractable in spec text and should be added, otherwise the plan author makes these decisions silently. The 25 edge cases can be triaged at plan-writing time *if* the spec is annotated with one-line dispositions for each.
dev/adversarial/2026-04-24-ruler-r5-codex.md:7:v2 fixes most of the Sonnet-round ship blockers, especially the Terrarium decode, z=12 rationale, touch-target sizing, and the move away from stale `useImperial` capture. It still is not plan-ready: there is one remaining integration bug that will double-fire reverse geocode when selecting ruler vertices in `editing`, and several spec claims are still underspecified or too optimistic about rerender triggers, style-hook accounting, font fallback, edge-case guards, and test rigor.
dev/adversarial/2026-04-24-ruler-r5-codex.md:15:#### C1. Editing-state vertex clicks still leak into the generic reverse-geocode handler
dev/adversarial/2026-04-24-ruler-r5-codex.md:25:It does not include any future ruler layers. So in `editing`, a click on `ruler-vertex-hit-circles` will do both things:
dev/adversarial/2026-04-24-ruler-r5-codex.md:27:- then fire the generic map click path and open the reverse-geocode popup
dev/adversarial/2026-04-24-ruler-r5-codex.md:32:- Add an explicit edit at the generic click handler so its `queryRenderedFeatures()` exclusion list includes the ruler hit/select layers, at minimum `ruler-vertex-hit-circles`, `ruler-vertex-circles`, and likely `ruler-line` if segment interactions are ever added.
dev/adversarial/2026-04-24-ruler-r5-codex.md:36:Why this is ship-blocking: selecting a vertex is core editing behavior. If every select click also pops a reverse-geocode card, the edit model feels broken.
dev/adversarial/2026-04-24-ruler-r5-codex.md:72:Spec §D requires `text-font: ['Metropolis Regular']` for `ruler-vertex-labels` and repeats that rule in the pitfalls checklist (spec lines 202, 430). That is not the prevailing style contract in the shipped tileserver styles.
dev/adversarial/2026-04-24-ruler-r5-codex.md:75:- `tileserver/styles/positron/style.json:662` → `["Metropolis Regular", "Noto Sans Regular"]`
dev/adversarial/2026-04-24-ruler-r5-codex.md:76:- `tileserver/styles/darkmatter/style.json:743` → `["Metropolis Regular", "Noto Sans Regular"]`
dev/adversarial/2026-04-24-ruler-r5-codex.md:82:- Change the ruler symbol layer to `text-font: ['Metropolis Regular', 'Noto Sans Regular']`.
dev/adversarial/2026-04-24-ruler-r5-codex.md:87:#### M4. Terrarium decode is fixed, but no-data / impossible-value guards are still missing
dev/adversarial/2026-04-24-ruler-r5-codex.md:90:A raw Terrarium decode of `(0,0,0)` yields `-32768m`. If a tile edge, transparent pixel, corrupted read, or unexpected sentinel leaks through, that value will dominate min/max and likely gain/loss too. The spec currently says only “compute min/max/gain/loss on non-null samples” (spec line 312), but it never defines when a decoded sample becomes `null` for being impossible.
dev/adversarial/2026-04-24-ruler-r5-codex.md:96:- Add explicit tests for `(0,0,0)`, alpha-zero pixels, and out-of-range decoded heights.
dev/adversarial/2026-04-24-ruler-r5-codex.md:115:- Expand the app.js enforcement test to verify the generic-click exclusion includes ruler layers or an equivalent claimed-click contract
dev/adversarial/2026-04-24-ruler-r5-codex.md:130:- “Gloved fingers”: 8/10 first-attempt taps on a vertex must select without opening a reverse-geocode popup.
dev/adversarial/2026-04-24-ruler-r5-codex.md:165:The test filename in §Testing still says `test_terrain_rgb.js` even though the whole point of R1/R2/R4 was that these are Terrarium tiles, not Mapbox Terrain-RGB. Rename it to `test_terrarium_decode.js` or `test_elevation_decode.js`.
dev/adversarial/2026-04-24-ruler-r5-codex.md:170:- Terrarium decode: fixed correctly in §E.3. This was the biggest v1 math bug.
dev/adversarial/2026-04-24-ruler-r5-codex.md:190:- Terrarium guard rails: they corrected the formula but left the no-data/impossible-value path underspecified.
dev/adversarial/2026-04-24-ruler-r5-codex.md:198:- one edit in the generic click handler’s feature-hit exclusion list for ruler layers in `editing`
dev/adversarial/2026-04-24-ruler-r5-codex.md:202:- “Vertex-clicks in `editing` are claimed by ruler and MUST NOT reach reverse-geocode. The generic click handler excludes ruler layers from its `queryRenderedFeatures()` gate.”
dev/adversarial/2026-04-24-ruler-r5-codex.md:209:- `text-font: ['Metropolis Regular', 'Noto Sans Regular']`

exec
/bin/bash -lc "grep -RInE \"pricing constants|Opus 4|\\"'$15/'"\\"'$75|5'"\\.6x|double-count|streaming partial|message\\.id|cache-write exclusion|ccusage|cache reads|reproducibility\" dev/adversarial/2026-04-25-cost-methodology-r*.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:5:**Scope:** scripts/audit_inference_cost.py + spec §4.2-4.3 + audit output reproducibility
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:15:#### C1 — Opus 4.x pricing constants are wrong by 3x on output
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:26:Anthropic's published rates for Claude Opus 4.5, 4.6, and 4.7 are **$5/M input, $25/M output** — not $15/$75. The $15/$75 rate applies to Claude Opus 4.0 and 4.1, which are not present in this corpus.
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:28:**Verification source:** https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching (pricing table, confirmed 2026-04-25 via WebFetch). Also confirmed by `npx ccusage` model pricing database (2684 models loaded). The prompt-caching doc explicitly lists:
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:32:| Opus 4.7 | $5/MTok | $6.25/MTok | $10/MTok | $0.50/MTok | $25/MTok |
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:33:| Opus 4.6 | $5/MTok | $6.25/MTok | $10/MTok | $0.50/MTok | $25/MTok |
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:35:**Corpus:** Production transcripts contain only `claude-opus-4-6` (20,603 turns) and `claude-opus-4-7` (16,128 turns). Zero turns from Opus 4.0 or 4.1. The wrong rate applies to 100% of Opus charges.
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:51:#### C2 — Output tokens are double-counted due to streaming partial records
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:59:Both records carry the same `message.id`. The script sums every usage-bearing record without deduplication, so a response generating 232 output tokens is counted as ~235 (1 streaming + 234 final, or similar). Across the full corpus:
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:90:- Opus 4.0/4.1: $15/M input, $75/M output (the "legacy" rate)
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:91:- Opus 4.5/4.6/4.7: $5/M input, $25/M output (the "current" rate)
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:93:If the corpus ever contains a mix (e.g., a project that started on Opus 4.1 before the upgrade), both generations get the same rate — whichever is hardcoded. Fixing C1 by changing the constant to $5/$25 would then undercount any Opus 4.0/4.1 turns. The correct fix is per-model-ID pricing, not tier buckets:
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:107:Note: this project's corpus contains only Opus 4.6 and 4.7, so after fixing C1 to $5/$25, M1 does not affect this project's specific numbers — but the methodology claims to be a reusable script that "any reader can invoke on their own `~/.claude/projects/*/`", so correctness matters for the general case.
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:149:The script increments `turns` for every usage-bearing JSONL line. Because streaming emits 2–5 records per logical response (the ratio varies by tool-use complexity), the "Turns" figure in the output table is overstated by the same factor as output tokens. For Opus, the dedup ratio is 29.7M raw output → 15.0M deduped output (roughly 2× inflation). Calling these "turns" in the README summary table misleads readers about how many actual interactions occurred. The column should either be renamed "API records" or the counting logic should deduplicate by `message.id`.
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:214:The headline number produced by the current script is wrong by 5.6× on the uncached figure and 5.4× on the full list price, due to the compound effect of wrong Opus pricing (C1) and output token double-counting (C2). Both must be corrected before any number appears in public documentation.
dev/adversarial/2026-04-25-cost-methodology-r1-math.md:219:2. **C2:** Deduplicate by `message.id` before accumulating token counts; take the max (or last-seen) `output_tokens` per ID and the same-across-all `input_tokens`.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:17:The audit script's `PRICING["opus"]` is set to `{"input": 15.0, "output": 75.0}` — the price for Claude Opus 4.1 (`claude-opus-4-1-20250805`). But the models actually used in these sessions are `claude-opus-4-6` (20,603 turns) and `claude-opus-4-7` (16,144 turns). Per LiteLLM's current pricing data (which ccusage fetches from `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`), both models are priced at:
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:24:This was independently verified by cross-checking ccusage's computed cost against the token counts:
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:28:At $5/$25/$6.25/$0.50: $1.00 + $51.89 + $186.50 + $1,599.00 = $1,838.39 ✓ (matches ccusage)
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:57:#### C2 — ccusage shows $3,430 total across ALL projects; no per-project breakdown available
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:59:`ccusage` is installed (`npx ccusage`) and produces a total cost across **all** Claude Code projects on this machine. Current output:
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:67:However, the spec (§4.3) claims "the $2,489 number ... any reader can reproduce with `ccusage`." This claim is false on two counts:
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:69:1. `ccusage` (with correct model pricing) gives ~$776 for geographica, not $2,489.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:70:2. `ccusage` without a `--project` filter returns all projects combined, not just geographica.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:72:A reader who runs `ccusage` expecting to reproduce "$2,489" will get ~$3,430 (all projects, correct rates) and conclude the methodology is inconsistent with the tool it cites. Existing R3 reviewer (flint) flagged the "appeal-to-tool" framing; this finding adds a concrete reproduction failure on top.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:102:When the pricing error is corrected, the "full list" number that ccusage computes (~$3,430 for all projects) becomes comprehensible as roughly $3,170 for geographica — close to the corrected $6,803 "full" (difference explained by the fact that ccusage uses a flat cache write rate and doesn't distinguish 5m/1h tiers, while the audit script does).
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:108:The only other Claude Code project on this machine is `tuxlink` (~350 Opus turns, ~$260 full cost at correct rates). This is an unrelated project started April 23, 2026 — after the Geographica project was well underway. Exclusion from the Geographica audit is correct, but the methodology should explicitly document the project boundary ("transcript directory: `~/.claude/projects/-home-administrator-Code-geographica/`; other projects on this machine, e.g. tuxlink, are excluded"). Without this documentation, a reader reproducing the audit who runs `ccusage` without a project filter will see ~$3,430 and question why it doesn't match.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:122:26 turns have `output_tokens=0` (rate-limited or aborted). Of these, 6 have non-zero `cache_read_input_tokens`. The audit script counts `cache_r` for these turns regardless of `output_tokens`, so they ARE included in the "full list price" calculation. This is correct behavior — these cache reads were billed. Not a gap.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:126:The transcripts contain 13 turns with `model="<synthetic>"` — internal Claude Code test/mock turns. `model_tier("<synthetic>")` returns `None`, so these are excluded. Token counts for synthetic turns are all zeros, so exclusion has zero dollar impact. Acceptable, but the methodology should document this exclusion class for reproducibility.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:143:- Zero-output turns: 26 total; 6 have cache reads which are correctly counted. No billing gap.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:154:**Blocker 1 (C1):** Fix the pricing constants. `claude-opus-4-6` and `claude-opus-4-7` are priced at $5/M input / $25/M output, not $15/$75. All headline numbers in the audit script, the spec, and the planned methodology page are wrong by approximately 3×. The correct headline is **~$776 uncached** and **~$6,803 full list price**. The audit script, PRICING dict, model_tier function, test assertions, and spec numbers all need updating before any public claim is made.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:156:**Blocker 2 (C2 + M1):** The methodology page cannot claim "`ccusage` reproduces this number" — it does not, and the reproduction path is broken in multiple ways (wrong model pricing, multi-project scope, stale spec numbers). The page should instead describe the calculation methodology and note that Codex sessions (covered by ChatGPT Plus) are excluded with a brief characterization of their volume.
dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:158:Once C1 is fixed, the new numbers (~$776 / ~$6,803) are actually *more* compelling for the pitch — the project consumed a fraction of what Opus 4.1 API rates would suggest, because Anthropic introduced cheaper successor models (Opus 4.6, 4.7) during the build. This is itself a story worth telling in the methodology page.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:19:**Steel-man:** Cache writes are real, billable tokens that the *model processed at full rate* to produce a cached representation. The Anthropic API charges for them because they represent actual compute work. When the methodology says "uncached input + output = the model's actual generation work," that is false: cache writes *are* generation work. The `cache_creation` field in the usage object is not advisory; it is a line item on the bill. Excluding it produces a number that is lower than what the model actually did, by the methodology's own claimed standard. A reader who knows the API will immediately notice that `$2,250 + cache_write_cost ≠ $2,250`, and the document gives them no principled reason for the exclusion beyond "this matches ccusage."
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:27:#### C2 — "Matches ccusage" is appeal-to-tool, not appeal-to-billing-truth
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:29:The methodology spec says the $2,489 number "matches what `ccusage` reports." `ccusage` is a third-party community tool with no Anthropic affiliation. Its treatment of cache tokens is a convention adopted by its maintainer, not an Anthropic-endorsed definition of "model work." If Anthropic's own invoices or dashboard reported a different number, `ccusage` alignment would be irrelevant.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:31:**Steel-man:** A skeptical reader will ask: does Anthropic's official billing dashboard show $2,489 or something else? If the answer is "we don't know — we're on Max, not API billing," then the $2,489 figure cannot be "verified by ccusage" against any ground truth; it is only internally self-consistent. The claim "matches ccusage" proves nothing about whether $2,489 is the right number — it only proves two tools agree on the same inputs with the same convention.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:33:**Does the methodology defend this?** No. The spec says "matches ccusage" as if that is a validation step, but ccusage cannot independently validate a number it contributed to computing.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:35:**Severity:** CRITICAL. Either drop the ccusage mention, or reframe it as "calculated using the same convention as ccusage" rather than "verified by ccusage."
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:39:#### C3 — The "harness artifact" claim about cache reads is load-bearing but unsupported
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:41:The methodology pivots on the claim that cache reads are a "harness artifact" — overhead generated by Claude Code re-loading context, not work the user requested. This justifies excluding them from the headline. But the spec does not prove this claim; it asserts it.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:45:1. *Cache reads aren't free*. Anthropic charges $1.50/M for cache reads. They appear on API bills. Calling them "artifact" while simultaneously citing their cost ($12K of the $22K full price) implies you're billing Anthropic for an artifact they charge you for. The framing looks like "we want the number to be small, so anything that makes it large is redefined as overhead."
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:47:2. *If you switched harnesses, you'd lose the benefits*. The cache reads exist because Claude Code re-uses a large persistent context window across turns. That context is why agents can hold a full codebase in working memory, why they don't need to re-read files every turn, why session startup is fast. Calling the cache reads a "harness artifact" implies you could eliminate them while keeping the quality. You cannot. The cache reads *are* what you bought. Excluding them from the cost is like a taxi passenger claiming the fuel cost is a "vehicle artifact" because they could have walked.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:49:3. *"50% reduction" is unverifiable*. If the methodology claims a different harness would reduce cache reads by ~50% (per the prompt framing), that needs to be demonstrated, not asserted. Without receipts — a concrete calculation or a second run with a different tool — it is handwaving.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:53:**Severity:** CRITICAL. The methodology needs either (a) a principled definition of what counts as "model work" that places cache reads outside it, or (b) honesty that this is a judgment call with a stated rationale.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:71:**For engineering leadership:** They understand billing. They will know cache reads exist and are charged. Showing $2,500 without immediately acknowledging the $22K makes them skeptical before they reach the methodology page.
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:191:### For C2 (ccusage framing)
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:193:Replace "matches ccusage" with:
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:195:> "This definition — uncached input plus output — is the same convention used by the community tool `ccusage`. It is not an Anthropic-endorsed definition; it is a deliberate choice to measure productive generation separately from cache overhead. The audit script ships with this repository so any reader can inspect and challenge the convention."
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:197:### For C3 (cache reads as harness artifact)
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:213:### For M3 (reproducibility honesty)
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:231:The structural decisions (two-number disclosure, separating cache reads from headline, shipping the audit script) are correct. But three issues would be raised immediately by a well-informed reader and are not pre-empted by the current spec:
dev/adversarial/2026-04-25-cost-methodology-r3-framing.md:234:2. The ccusage citation validates nothing without a principled definition backing it.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:37:- Opus 4.x:   $15/M input, $75/M output, cache 5m=$18.75/M (1.25x), cache 1h=$30/M (2x), cache read=$1.50/M (0.10x)
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:41:The methodology page will define the "headline" number as: uncached input + output for all tiers, summed. The "full list price" includes cache reads/writes at full Anthropic API rates.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:45:1. **Pricing-source verification.** Independently look up Anthropic's documented per-token rates as of 2026-04 for Opus 4.x, Sonnet 4.x, and Haiku 4.5. Are the constants in the script correct? Are there model variants (e.g., "extended thinking", "1M context") with different rates that the script's substring matching ("opus" in model_id) would conflate?
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:51:4. **Subagent token counting.** The script enumerates parent transcripts (top-level *.jsonl) and subagent transcripts (*/subagents/*.jsonl). From a fresh perspective: is this the right boundary? Could subagent costs be already double-counted (e.g., reflected in a parent's "cache write" when the subagent's tool result returns)? Or under-counted (e.g., subagents that didn't get their own .jsonl because they failed mid-stream)?
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:153:  - "uncached" = input + output only (matches ccusage convention)
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:154:  - "full"     = above + cache writes (1.25x or 2x input) + cache reads (0.1x input)
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:397:The full $21,858 list-price number is **not** in the README. It lives in `docs/COST_METHODOLOGY.md` with full reasoning: cache reads dominate the list price, cache reads are a harness artifact (not work), the $2,489 number is the honest "model work" measure that any reader can reproduce with `ccusage` or the included audit script. No lie of omission, but the headline is the meaningful number.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:512:| 1 | Headline number ($2,489) | API-equivalent model output (uncached input × $15/M + output × $75/M for Opus, proportional rates for Sonnet/Haiku); matches what `ccusage` reports |
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:513:| 2 | Full list-price number ($21,858) | Headline + cache-read tokens (8.1 B at $1.50/M = $12.1K) + cache-write tokens (110 M at $18.75–$30/M = $3.3K); explains cache reads are a harness artifact |
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:554:Some peers will read "~$2.5K" in the README, click through to `COST_METHODOLOGY.md`, see "$22K", and conclude the README is misleading. **Mitigation:** the methodology page leads with the headline number being the honest one and cache reads being overhead — but the framing depends on the reader trusting the explanation. **Acceptance:** this is the cost of being honest; the alternative (omitting the $22K) would be worse.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:587:     9	  - "uncached" = input + output only (matches ccusage convention)
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:588:    10	  - "full"     = above + cache writes (1.25x or 2x input) + cache reads (0.1x input)
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:1776:There’s a more serious question than pricing constants: the script treats every usage-bearing assistant JSON object as a billable “turn.” In the real transcript format, one user turn often produces multiple assistant objects (`thinking`, `text`, `tool_use`), so I’m checking whether those `usage` fields are incremental or cumulative. If they’re cumulative, the entire cost audit is overstated.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2220:The biggest defect is confirmed: repeated transcript fragments share the same `message.id` and the same `usage` payload, but the script adds them every time. This is not a small off-by-one; it means the current methodology is charging the same model response multiple times whenever a single answer emits `thinking`, `text`, and one or more `tool_use` entries.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2453:Anthropic’s current pricing docs changed in exactly the place this script hard-codes most aggressively: Opus 4.6/4.7 are not priced like Opus 4.1/4.0 anymore. Since the local corpus is dominated by `claude-opus-4-6` and `claude-opus-4-7`, a tier-level `"opus" => $15/$75` rule now materially overstates cost even before the duplicate-counting bug.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2597:    62	The full $21,858 list-price number is **not** in the README. It lives in `docs/COST_METHODOLOGY.md` with full reasoning: cache reads dominate the list price, cache reads are a harness artifact (not work), the $2,489 number is the honest "model work" measure that any reader can reproduce with `ccusage` or the included audit script. No lie of omission, but the headline is the meaningful number.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2634:1. **The script double-counts the same billed response multiple times.**  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2635:   In `scripts/audit_inference_cost.py:55-81`, every JSONL line with `message.usage` is summed as a fresh billable turn. Real Claude Code transcripts reuse the same `message.id` across `thinking`, `text`, and one or more `tool_use` fragments, and those fragments carry the same `usage` payload.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2637:   This is not hypothetical. On the current local corpus, naive counting produced about `$2,263.57` uncached / `$19,865.02` full, while deduping by `(file, message.id)` produced about `$824.31` uncached / `$10,478.28` full.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2640:2. **The Opus pricing constants are stale and materially wrong for the models actually present in the corpus.**  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2641:   `scripts/audit_inference_cost.py:21-25` prices all `"opus"` as `$15/M` input and `$75/M` output. Anthropic’s current pricing page lists **Claude Opus 4.7, 4.6, and 4.5 at $5/M input and $25/M output**, while only **Opus 4.1 and Opus 4** remain at `$15/M` / `$75/M`.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2652:   - Opus 4.6 fast mode at premium pricing.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2653:   - US-only `inference_geo` 1.1x pricing for Opus 4.6/4.7 and newer.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2679:   I found no evidence that `*/subagents/*.jsonl` is intrinsically double-counting parent costs. The real double count is inside each file via repeated `message.id`. I also found no evidence of “meta-only failed subagents” that would create a significant undercount; local `subagents/*.meta.json` all had matching `subagents/*.jsonl`.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2685:- **Opus 4.7 / 4.6 / 4.5:** `$5/M` input, `$25/M` output, cache write/read multipliers applied from that base.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2687:- **Opus 4.1 / 4.0:** `$15/M` input, `$75/M` output.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2695:- **US-only inference premium:** `1.1x` for Opus 4.6/4.7 and newer when `inference_geo` is specified.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2697:- **Fast mode premium:** Opus 4.6 fast mode at 6x standard rates.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2701:- **1M context caveat:** current docs say Opus 4.6/4.7 and Sonnet 4.6 include 1M context at standard pricing.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2714:1. Deduplicate usage by unique response identity, at least `(filepath, message.id)`.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2722:6. Add tests that simulate repeated fragments with the same `message.id` and identical `usage`; current tests do not cover the dominant failure mode.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2745:1. **The script double-counts the same billed response multiple times.**  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2746:   In `scripts/audit_inference_cost.py:55-81`, every JSONL line with `message.usage` is summed as a fresh billable turn. Real Claude Code transcripts reuse the same `message.id` across `thinking`, `text`, and one or more `tool_use` fragments, and those fragments carry the same `usage` payload.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2748:   This is not hypothetical. On the current local corpus, naive counting produced about `$2,263.57` uncached / `$19,865.02` full, while deduping by `(file, message.id)` produced about `$824.31` uncached / `$10,478.28` full.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2751:2. **The Opus pricing constants are stale and materially wrong for the models actually present in the corpus.**  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2752:   `scripts/audit_inference_cost.py:21-25` prices all `"opus"` as `$15/M` input and `$75/M` output. Anthropic’s current pricing page lists **Claude Opus 4.7, 4.6, and 4.5 at $5/M input and $25/M output**, while only **Opus 4.1 and Opus 4** remain at `$15/M` / `$75/M`.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2763:   - Opus 4.6 fast mode at premium pricing.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2764:   - US-only `inference_geo` 1.1x pricing for Opus 4.6/4.7 and newer.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2790:   I found no evidence that `*/subagents/*.jsonl` is intrinsically double-counting parent costs. The real double count is inside each file via repeated `message.id`. I also found no evidence of “meta-only failed subagents” that would create a significant undercount; local `subagents/*.meta.json` all had matching `subagents/*.jsonl`.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2796:- **Opus 4.7 / 4.6 / 4.5:** `$5/M` input, `$25/M` output, cache write/read multipliers applied from that base.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2798:- **Opus 4.1 / 4.0:** `$15/M` input, `$75/M` output.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2806:- **US-only inference premium:** `1.1x` for Opus 4.6/4.7 and newer when `inference_geo` is specified.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2808:- **Fast mode premium:** Opus 4.6 fast mode at 6x standard rates.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2812:- **1M context caveat:** current docs say Opus 4.6/4.7 and Sonnet 4.6 include 1M context at standard pricing.  
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2825:1. Deduplicate usage by unique response identity, at least `(filepath, message.id)`.
dev/adversarial/2026-04-25-cost-methodology-r5-codex.md:2833:6. Add tests that simulate repeated fragments with the same `message.id` and identical `usage`; current tests do not cover the dominant failure mode.

exec
/bin/bash -lc "grep -RInE \"distanceToManeuver|negative TTM|start\\(|checkVoice\\(|currentManeuverIdx|no nav-ui changes|G7|deterministic|3 prompts\" dev/adversarial/2026-04-20-nav-voice-ttm-r*.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:13:The single most severe bug is F1.1: `distanceToManeuver` in the current codebase returns a *signed* along-route difference. The spec assumes non-negative. Under GPS jitter, U-turn maneuvers with overlapping `begin/end_shape_index`, or a dead-reckoning extrapolation that walks past the next maneuver's begin-shape before `currentManeuverIdx` advances, `distToNext` goes negative → `ttm = negative / positive = negative` → `ttm <= 30` is trivially true → far-tier fires for a maneuver the driver has already executed or is in the middle of executing. This is exactly the "wrong prompt, wrong time" failure mode the spec is trying to eliminate.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:17:### F1.1 — `distanceToManeuver` can return negative; negative TTM passes every threshold
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:34:`distanceToManeuver(snap, maneuverIdx)` at `navigation.js:309-313` wraps this without a `Math.max(0, …)` guard. It returns a negative number whenever the snap's along-route position exceeds the target maneuver's `begin_shape_index` position. Four realistic ways this happens:
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:37:2. **Dead-reckoning overshoot.** `deadReckonTick()` at `navigation.js:686-700` calls `checkVoice(drSnap)` where `drSnap` is an extrapolated position. During a 30-second DR window at 15 m/s, the DR snap advances 450m. If the next maneuver is 300m away, the DR snap walks 150m past it — `distToNext < 0` — AND `currentManeuverIdx` may lag because `findManeuverForSegment` is called on the DR snap just before checkVoice. Under the spec's D1 suppression, a negative TTM makes the near-tier condition trivially true → near fires → `announcedSet[nearKey] = true` → real GPS returns → near already "announced" → driver never hears the turn they should have heard at the real 30s point.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:38:3. **GPS jitter at a maneuver boundary.** Snap bounces between seg *N-1* and seg *N* across two ticks. If seg *N* is the first segment of the next maneuver, tick 1 sees `targetIdx > segIdx` (fine), tick 2 sees `targetIdx <= segIdx` (negative). Under the band-aid's 3-tier model this is masked by the distance-based check (400m threshold); under TTM, a negative TTM passes every threshold simultaneously.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:47:   var distToNext = Math.max(0, distanceToManeuver(snap, nextIdx));
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:49:2. Early-return when `distToNext === 0` AND `currentManeuverIdx` still reports the pre-maneuver index (a sentinel that the snap is at-or-past the boundary but state hasn't caught up):
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:56:**Sources:** `frontend/navigation.js:209-214` (`distanceToCoordIndex`), `frontend/navigation.js:309-313` (`distanceToManeuver`), `frontend/navigation.js:686-700` (`deadReckonTick`). Valhalla U-turn maneuver docs: https://valhalla.github.io/valhalla/api/turn-by-turn/api-reference/#maneuver-types (types 16/17 = uturn_right/left, shape-index semantics undocumented by Valhalla).
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:77:This is not directly a correctness bug *if* the invariants are "fires at or near the threshold." But I1/I2's claim of **"Exactly 2"** / **"Exactly 1"** announcements is tested against a simulator, and a deterministic simulator with integer-arithmetic speed (10.0 m/s exactly) will pass while a realistic noisy-speed simulator fails intermittently. The spec does not define simulator speed semantics — `simulateApproach({speed, entryDist, costing, steps})` in §6.1 is silent on whether `speed` is the deterministic tick-to-tick step or the mean of a noisy stream.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:86:2. §6.1: specify that `simulateApproach` uses deterministic integer-tick advancement (no noise) and document that noisy-stream behavior is covered by §6.2 outlier test. Or: add a §6.7 "Threshold-boundary jitter" test that injects ±0.5 m/s GPS noise over a 30-tick approach and asserts far-tier fires within a ±1-tick window of the noise-free baseline.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:107:Step 5 immediately enters `tick()`, which calls `pushSpeedSample(gpsSpeed)` (§4.2 integration claim). At entry to `checkVoice()`, `speedSamples.length === 1` (the just-pushed sample). `speedMedian()` returns `sorted[0] = thatSingleSample`. If the driver was rerouted *because* GPS showed off-route (which is the triggering condition for most reroutes), the sample that caused the reroute may be anomalous — an outlier spike from stale Bluetooth pairing with a phone, a multipath echo, or the classic cold-start-GPS 50-m/s phantom velocity. The reroute-induced re-tick uses that single anomalous sample as the median.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:118:2. §4.3 (alternative): skip `checkVoice(snap)` entirely on the re-tick that `applyReroute` triggers. Add a `skipVoice` flag parameter to `tick()`. The re-tick's purpose is to push UI state and advance the snap; it does not need to fire voice prompts on the same frame as the reroute. The first *naturally-arriving* GPS tick after reroute (≤ 1 second later) will have `speedSamples.length === 1` still, but by tick 3 we're at full median. Delaying voice by 1-3 seconds post-reroute is operationally invisible.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:131:**Reality:** D1 assumes that "near fires" implies "driver is actively executing this maneuver imminently." That's true for the maneuver the driver is *approaching*. But `announcedSet` is keyed on `nextIdx = currentManeuverIdx + 1` — the **single** maneuver ahead. Consider this sequence:
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:135:3. Driver executes M. `currentManeuverIdx` advances. New `nextIdx = M+1`.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:141:1. Driver approaches M, 40m at 10 m/s. Near fires for M, D1 suppresses far for M. `currentManeuverIdx` incremented.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:144:4. Next tick: driver moves to 30m from M. `currentManeuverIdx` is still M-1 (driver hasn't executed M yet). `nextIdx = M`. `announcedSet['M-near']` is true → `nearWouldFire` false. `announcedSet['M-far']` is true → `farWouldFire` false. Nothing fires. Driver passes M.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:145:5. Driver executes M. `currentManeuverIdx = M`. `nextIdx = M+1`. Driver is now 30m from M+1 (it's a close pair). TTM = 30/10 = 3s = near threshold. Dist = 30m ≤ 50m floor. Near fires for M+1. Far suppressed. **Driver hears 2 prompts (one for M, one for M+1) in 30m of driving — fine.** Matches §6.4 Villa Rita scenario.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:168:So the actual finding is subtler: **D1 suppression is correct in the core case, but the spec's I2 prose conflates "driver enters inside near-tier" with "driver is close when the tick arrives." For the latter to be unambiguous, the spec must assert that `announcedSet` is cleared on maneuver index advance — which it implicitly is (keys are per-nextIdx), but this invariant is not called out.** If a reader re-implements D1 keyed on `currentManeuverIdx` (the maneuver the driver is ON, not the next one), D1 bleed-over between maneuvers becomes possible.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:170:**Impact:** Low in the reference implementation as specified. But the spec's invariants I1/I2 are asserted as "by construction" — and the construction depends on the keying being `nextIdx`-scoped. A sloppy re-implementation that uses `currentManeuverIdx` as the D1 key (seemingly equivalent) would break I1 after the first near-fire.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:174:1. §4.3 add a comment: "`announcedSet` keys use `nextIdx` (the upcoming maneuver), NOT `currentManeuverIdx` (the maneuver the driver is on). D1 suppression only affects the single upcoming maneuver and does not bleed across maneuver boundaries."
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:253:**Claim in spec:** §E7: "`deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap. `lastSpeed` from the last real GPS tick is used by DR's extrapolation but `speedMedian()` reads `speedSamples` — these do not update during DR. TTM during DR uses the last-real-median. Acceptable: GPS outage is rare and DR is short-lived (≤30s per `DEAD_RECKON_MAX`)."
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:272:2. More defensible: skip `checkVoice()` during DR entirely. Add a `skipVoice` parameter to `checkVoice()` or gate the call site. Voice prompts can resume when real GPS returns. §G5 already accepts "short-lived DR" as an edge case; extending that to "no voice during DR" is a clean degradation.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:280:### F1.8 — G2 claim "Villa Rita: 3 maneuvers → 3 prompts" assumes a specific route topology; the spec does not verify that the Villa Rita scenario meets the assumption
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:284:**Claim in spec:** §1, §G2, §6.4 all assert "Villa Rita post-reroute 3-maneuver cluster: 3 prompts total (one near-tier per maneuver; far suppressed by D1), down from 9."
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:289:- Tick 2: driver at 20m from M1 (moved 10m in 1 sec). Near fires?  Actually M1's near is already announced. Nothing for M1. After M1 execution (say at tick 4), currentManeuverIdx advances.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:291:- On tick 4, currentManeuverIdx = M1; nextIdx = M2. TTM = dist-to-M2/speed. If driver is between M1 and M2 at dist=15m (passed M1, approaching M2), TTM = 1.5s — near fires for M2. D1 suppresses far. And so on.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:293:Count: one near per maneuver = 3 prompts. **Matches §G2.** Good.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:298:- Tick 2: driver at dist 30 from M1. currentManeuverIdx still pre-M1. Near already fired. Nothing.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:299:- Tick 3: driver past M1 (dist=0 or negative per F1.1!). currentManeuverIdx = M1. nextIdx = M2. dist-to-M2 = 20-10 = 10m at 10 m/s. Near fires for M2.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:302:Count: 3 prompts. Still matches. But: F1.1's negative-distance risk applies at every maneuver transition in this dense cluster. If at tick 3 the snap reports `dist-to-M2 = -5m` (snap walked past M2's begin_shape_index before currentManeuverIdx advanced), and the computed TTM is negative, and `announcedSet[M2-far]` is fresh, far *fires first* at the negative-TTM tick — adding a spurious prompt BEFORE the near fires on tick 4.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:304:**Impact:** Under F1.1's negative-distance bug, §G2's "3 prompts, down from 9" can regress to 4-5 prompts in the dense Villa Rita cluster — better than 9 but worse than the spec claims.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:306:**Proposed fix:** After fixing F1.1, re-verify §6.4's test synthesizes a snap sequence that includes the maneuver-transition boundary (`segmentIndex === m.end_shape_index` on tick N, → `segmentIndex === m.end_shape_index + 1` on tick N+1, with `currentManeuverIdx` advancing on tick N+1 via `findManeuverForSegment`). Assert that no spurious prompts fire during this 1-tick transition window.
dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:318:Total: 8 findings across 3/4/1 severity tiers. The spec's algorithmic frame is sound — TTM is the right unit, D1 suppression halves announcement rate in dense clusters correctly — but the realism of `distanceToManeuver`'s sign, the timing of re-tick after reroute, and the breadth of the speed-smoothing window need hardening before ship.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:104:**Claim in spec:** §E7 states: "`deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap. `lastSpeed` from the last real GPS tick is used by DR's extrapolation but `speedMedian()` reads `speedSamples` — these do not update during DR. TTM during DR uses the last-real-median."
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:109:- `deadReckonTick` calls `checkVoice(drSnap)` using the DR'd snap position.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:115:3. t=4s: Stale-checker fires (≥3s). `deadReckonTick()` runs. DR extrapolates: user has moved 30m in 3s at lastSpeed=10m/s. New drSnap has distance to maneuver 1 ≈ 10m (or past it, depending on geometry). `checkVoice(drSnap)` runs — but maneuver 1 is already marked in `announcedSet`, so it's a no-op. Good.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:116:4. t=5s: Real GPS comes back. `updateGPS` fires. `tick()` runs on the new real snap. But depending on how far the user actually moved during outage, `currentManeuverIdx` may have advanced past maneuver 1 to maneuver 2.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:117:5. L573: `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`. If this now equals 2 (user passed maneuver 1 during outage), `checkVoice` computes `nextIdx=3`, looks at maneuver 3. No conflict.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:118:6. **But** what if the DR'd snap in step 3 was already at maneuver 2's segment (user crossed during outage)? `deadReckonTick` L697: `currentManeuverIdx = findManeuverForSegment(drSnap.segmentIndex)`. Now `currentManeuverIdx=2`. `checkVoice` for maneuver 3 runs. If it's close enough, fires a prompt. User hears "turn right onto Elm" during GPS outage. Fine.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:119:7. t=5s real GPS: `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)` — may still be 2 (user is between maneuver 2 and 3). `checkVoice` sees `announcedSet["3-near"]=true` from DR → no-op. Good — but only because D1 marked both keys during DR.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:129:This mostly works, but there's an edge: **the `currentManeuverIdx` mutation in `deadReckonTick` at L697 is made against a DR'd position, which can be WRONG if GPS comes back showing user was actually OFF the route (took an off-ramp during outage).** Real GPS then triggers off-route detection and reroute — but `currentManeuverIdx` has already advanced under DR. If the real-GPS tick detects off-route at L620-641, `triggerReroute` fires. Then `applyReroute` resets `currentManeuverIdx=0`. Good — covered.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:131:**The actual latent bug:** `deadReckonTick` calls `checkVoice` with `drSnap`, which mutates `announcedSet` using `nextIdx = currentManeuverIdx + 1` where `currentManeuverIdx` was just set by DR. If GPS comes back and REAL `currentManeuverIdx` is LESS than DR's (e.g., DR over-estimated distance traveled), then `checkVoice` under real GPS looks at a DIFFERENT `nextIdx` than DR did. DR marked `announcedSet["3-far"]`; real GPS checks `announcedSet["2-far"]` (still false), fires maneuver 2's prompt, even though we already voiced maneuver 2 as part of the DR sequence. Double-announcement.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:135:- t=0: real snap segmentIndex=8, currentManeuverIdx=0. Fire far for maneuver 1.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:137:- t=4s: `deadReckonTick`. lastSpeed was high (say 20m/s from pre-outage). DR extrapolates 3s × 20m/s = 60m. drSnap.segmentIndex now =22. `currentManeuverIdx = findManeuverForSegment(22) = 2` (between maneuver 2 at 20 and maneuver 3 at 30). `checkVoice` fires maneuver 3's far (nextIdx=3). Maneuver 2's "far" was skipped entirely (we jumped from checking maneuver 1 to checking maneuver 3 with no tick at maneuver-2-eligible position). `announcedSet = {"1-far": true, "3-far": true}`. Note: "2-far" and "2-near" are false.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:138:- t=5s: real GPS shows user is at segmentIndex=15, currentManeuverIdx=1 (DR over-estimated). `checkVoice` with nextIdx=2. `announcedSet["2-far"]` false. Fires prompt for maneuver 2. Valid — user really did need that prompt (they're still approaching maneuver 2). But the DR prompt for maneuver 3 was **premature** — user was not actually past maneuver 2.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:140:**Impact:** (a) During GPS outage, DR'd prompts can fire for maneuvers the user has NOT actually reached; `announcedSet` now locks them out even if the user eventually arrives there. (b) If DR's `currentManeuverIdx` advances too fast (past the true position), maneuvers are **skipped entirely** in announcement state — the user will NEVER hear "turn left onto Oak" because `checkVoice` hops from maneuver 1 to maneuver 3 without visiting maneuver 2's far-tier threshold.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:309:### F2.7 — `currentManeuverIdx` can advance by >1 in a single tick; skipped maneuver's announcements never fire
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:313:**Claim in spec:** §4.3 checkVoice uses `nextIdx = currentManeuverIdx + 1`. Nothing addresses rapid advancement.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:315:**Race scenario:** Examining navigation.js L573: `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`. This is **derived** from the snap; no monotonicity check, no rate limit.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:318:2. t=0: Real GPS at segmentIndex=14. `currentManeuverIdx=1` (past maneuver 1, approaching 2). `announcedSet["2-far"]=true` fired last tick.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:320:4. Real GPS at segmentIndex=33. `currentManeuverIdx=3`. `nextIdx=4`. Maneuver 4 is checked. `announcedSet["4-far"]` may or may not fire.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:327:- Tick 2: `currentManeuverIdx=3`, `nextIdx=4`. Maneuver 4 checked. Maybe fires "4-far".
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:328:- Tick 3: `currentManeuverIdx=2`, `nextIdx=3`. Maneuver 3's "3-far" has never fired. If distance criteria met, it fires. OK.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:333:**Proposed fix:** In `checkVoice`, only allow announcements for `nextIdx = currentManeuverIdx + 1` if `currentManeuverIdx` advanced by ≤ 1 since the last tick. If advancement jumped >1, log and skip this tick's `checkVoice` (the next tick will catch up). OR: in `findManeuverForSegment`, add monotonicity — never return less than `currentManeuverIdx` (treating the index as sticky-forward). This protects against forward-then-back glitches.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:355:checkVoice(snap);   // L648
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:440:Specifically: in the spec's `tick()` integration (§4.2), `pushSpeedSample` is called "immediately after `lastSpeed = gpsSpeed;`". But `tick()` continues: snap, findManeuver, recordSpeed, off-route checks, arrival check, `checkVoice(snap)`. If a test calls `_getSpeedSamples()` from an earlier hook (e.g., a custom onUpdate callback invoked at `emitUpdate(buildState(snap, false))` at L650 — the FINAL line of tick()), then speedSamples is already fully updated. Good.
dev/adversarial/2026-04-20-nav-voice-ttm-r2-concurrency.md:513:**Most load-bearing for field safety:** F2.7 — `currentManeuverIdx` derived purely from `findManeuverForSegment(snap.segmentIndex)` is non-monotonic and rate-unlimited. GPS glitches that jump segment-index forward-then-back can lock future maneuvers' announcements. Recommend adding monotonicity to `findManeuverForSegment` (never return less than current) in the same PR, even though §NG4 declares reroute trigger logic out of scope — this is checkVoice-adjacent and directly affects G1/G2 invariant holding in field conditions.
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:90:   means `snapToRoute()`, `findManeuverForSegment()`, the `distanceToManeuver`
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:95:   `nav.start(route)` with a mocked window, then calls `nav.updateGPS(...)`
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:113:  2. Calls loadEngine() and nav.start(route).
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:233:Villa Rita → Costco...≤ 3 prompts."
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:241:   "exactly 3 prompts" assertion does not model. The synthetic passes;
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:257:(b) Loosen the §6.5 ship criterion to "≤ 3 prompts PER MANEUVER CLUSTER"
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:323:3 prompts across 3 maneuvers — but its ticks are spaced in simulated
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:325:cooldown, 3 prompts at 30-m spacing at 10 m/s are spaced 3 seconds of
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:457:`deadReckonTick()` calls `checkVoice(drSnap)` with the dead-reckoned snap.
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:496:route...Ship criteria: ≤ 3 prompts for the rerouted 3-maneuver cluster."
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:499:prompt count (e.g., a refactor of `distanceToManeuver`), nobody notices
dev/adversarial/2026-04-20-nav-voice-ttm-r3-testing.md:641:chain logic at §4.3 line 200 `distanceToManeuver({segmentIndex:
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:39:- `checkVoice()` is at `frontend/navigation.js:357-411` as claimed — OK today.
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:53:Task 3, the `navigation.js:357-411` reference for `checkVoice()` is wrong,
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:79:  body of `function checkVoice(snap) {` (the function starts at the
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:162:> 3. **Rewrite** `checkVoice()` (§4.3) — the new body references the new
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:261:- B) Nested inside `checkVoice()` (the only caller, arguably).
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:276:`speedMedian` is called from `checkVoice()`."
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:494:   `VOICE_COOLDOWN`, `checkVoice()` still references the other three.
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:503:   `checkVoice()` still calls `announce(text, key)` at
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:507:`checkVoice()` first, they have to land ALL the new code BEFORE deleting
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:528:> 3. **Rewrite `checkVoice()`**: replace the full function body with the
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:615:  that calls `deadReckonTick()` → `checkVoice(drSnap)` when GPS is
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:616:  stale. This is a SECOND entry into `checkVoice()` that §4.2 ignores —
dev/adversarial/2026-04-20-nav-voice-ttm-r4-executability.md:711:> 8. **§6.5 Villa Rita field re-drive** — ≤ 3 prompts for the 3-maneuver
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:18:experience Cameron thinks he's buying, or whether the "3 prompts from 9"
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:41:**Current spec position:** §1 and §6.4 both advertise "3 prompts for the
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:57:- **Tick advances `currentManeuverIdx` how?** The spec inherits
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:58:  `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:104:**Impact:** The §1 "3 prompts" number is real but load-bearing on the
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:125:not. Do not let §1 keep the "3 prompts" headline if it's only true
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:669:- Add to NG7 or new §NG10: "Auto-unmute on reroute is out of
dev/adversarial/2026-04-20-nav-voice-ttm-r5-product.md:696:observation. Count voice prompts. Ship criteria: Pass: ≤ 3 prompts
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:13:### F6.1 — The spec’s route-start guarantees do not hold on this engine’s actual `start()` path
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:19:**Reality / impact:** The live engine does not run the TTM pipeline on `start()`. In [frontend/navigation.js](/home/administrator/Code/geographica/frontend/navigation.js:758), `start()` snaps, stores `lastGPS`, sets `state`, and immediately `emitUpdate(buildState(...))`, but it does **not**:
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:20:- set `currentManeuverIdx` from the snap,
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:22:- call `checkVoice(snap)`.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:26:There is a second-order correctness issue too: `buildState()` reads `currentManeuverIdx`, but `start()` leaves it at the reset default `0`, so a mid-route start can render the wrong `nextManeuver` until the first movement tick.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:28:**Proposed fix:** The spec needs an explicit startup-initialization step, not just a `tick()` rewrite. On the on-route branch of `start()`:
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:29:- set `currentManeuverIdx = findManeuverForSegment(snap.segmentIndex)`,
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:31:- decide whether `checkVoice(snap)` is allowed on start or explicitly deferred.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:43:**Reality / impact:** The current UI wiring assumes `nav.start()` is voice-silent. In [frontend/nav-ui.js](/home/administrator/Code/geographica/frontend/nav-ui.js:154), the order is:
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:46:2. `nav.start(routeData)`
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:59:- Keep `start()` voice-silent and scope G2/G4 to post-start GPS ticks only.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:60:- Or allow start-time voice, but then `nav-ui.js` is in scope: move `nav.setMuted(muted)` before `nav.start(routeData)`, and re-evaluate whether `primeSpeech()` / wake-lock ordering must move too.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:62:Right now the spec promises both “route-start prompt works” and “no nav-ui changes,” but this codebase cannot satisfy both simultaneously.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:66:### F6.3 — The synthetic “3-maneuver cluster → 3 prompts” test is off by one against actual engine maneuver semantics
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:72:**Reality / impact:** This engine voices the **upcoming** maneuver at `nextIdx = currentManeuverIdx + 1`; it does not voice the maneuver you are already on. The existing fixture in [frontend/tests/engine/test_runner.mjs](/home/administrator/Code/geographica/frontend/tests/engine/test_runner.mjs:48) shows the convention clearly: a “3-maneuver route” is actually “2 turns + arrival,” and the first spoken turn is maneuver index `1`, not `0`.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:74:So a literal “3 maneuvers total” synthetic route cannot produce “3 spoken maneuver prompts” under current semantics unless you also change initialization semantics. With the current engine model, a “3 prompts in a close cluster” scenario needs either:
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:76:- an explicit change in how `currentManeuverIdx` is initialized for synthetic tests.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:88:### F6.4 — G7 overclaims determinism; this engine still depends on wall-clock scheduling, not just route + GPS values
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:92:**Quoted spec claim:** “**G7.** Behavior is deterministic: identical `(route, GPS stream)` inputs produce identical announcement counts and timing. No hidden cooldown or randomness.”
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:107:**Proposed fix:** Narrow G7 to something the implementation can actually guarantee, for example:
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:121:**Quoted spec claim:** “Villa Rita post-reroute 3-maneuver cluster: **3 prompts total**” and “Pass: **≤ 3 prompts** for the rerouted 3-maneuver cluster.”
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:139:If you want to keep NG5 as-is, then at least state explicitly that the “3 prompts” headline means “3 engine callbacks,” not “3 fully spoken utterances.”
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:149:**Reality / impact:** The spec repeatedly reasons about “route-start into a close maneuver” and “post-reroute into a close maneuver,” but this engine also supports starting while already on-route or partway through a route. On that path, [start()](/home/administrator/Code/geographica/frontend/navigation.js:758) currently emits UI state without reconciling `currentManeuverIdx` to the snap. That is not just a voice issue; it is a general navigation-state issue, and TTM makes it more visible because voice timing now depends on a correctly identified “next maneuver.”
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:151:If the spec is intentionally not fixing mid-route start semantics, it needs to say that. Otherwise implementers will assume the existing startup behavior is already valid and only patch `checkVoice()`.
dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:154:- either “TTM assumes `start()` is corrected to initialize maneuver state from the snap,”

codex
One thing already stands out: the draft is mostly careful on exclusivity, but there are a few places where the evidence trail is sloppier than the headline suggests. I’m checking one more cycle because I’ve already spotted at least one row whose cited file appears to contradict its own exclusivity label.
exec
/bin/bash -lc "sed -n '1,220p' dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
### F5.1 — Issue 3 should be split from the nav-voice PR
Severity: SHOULD-FIX
Claim: The spec’s “same PR for delivery cohesion” argument is weak for Issue 3. The document itself says Issue 3 is orthogonal, touches a different file (`frontend/app.js` vs `frontend/navigation.js`), has a different test harness (`tests/test_frontend_voice_picker.py` vs engine tests), and even implies a different change type (`fix(nav)` / `feat(nav)` / `fix(nav)` in one bundle). That is not one unit of risk; it is two unrelated risk surfaces coupled by a shared field drive.
Impact: Review, rollback, and release reasoning get muddier than they need to be. A regression in sidebar lifecycle handling can block shipping the voice fixes, or vice versa, even though the fixes do not depend on each other. It also makes it harder to interpret the Villa Rita gate: a pass on the drive validates Issues 1 and 2 directly, but only weakly exercises Issue 3.
Recommendation: Edit sections 1, 10, and 11 to make Issue 3 a separate PR/spec unless a repo-level constraint requires bundling. If Cameron insists on one merge train, the spec should still require separate commits, separate acceptance criteria, and an explicit statement that Issue 3 may be cherry-picked or reverted independently without invalidating the voice ship gate.

### F5.2 — The BFCache diagnosis is overstated and the proposed listener does not cover the full iOS return path
Severity: MUST-FIX
Claim: Section 6 treats BFCache as the primary cause and section 6.4 claims the `pageshow` listener gives “full cover over all page-lifecycle events.” That is too strong. `pageshow` with `persisted === true` only covers one return mode. Similar “sidebar reverted to default tab” symptoms can also come from `pageshow` with `persisted === false` after a tab discard or renderer recreation, standalone-PWA process recreation, `visibilitychange`/resume paths that partially rehydrate UI without rerunning the original restore point, or an interruption path where speech/audio/session code mutates visible state while the page returns. None of those are fixed by the proposed guard.
Impact: The PR can ship with a satisfying BFCache narrative while leaving the user-visible bug reproducible on other iOS Safari return paths. If that happens, the team will think the lifecycle bug is closed when it is only narrowed.
Recommendation: Rewrite sections 1, 6.1, 6.2, 6.4, 7, and 9 to narrow the claim from “primary cause / full cover” to “one confirmed return path,” and add one of these spec changes:
- Preferred: restore sidebar state from a lifecycle-agnostic reconciliation point such as sidebar-open, `pageshow` regardless of `persisted`, or `visibilitychange` when returning to `visible`, with an idempotent guard.
- Minimum: add explicit non-goals for `persisted === false`, standalone-PWA recreation, and tab-discard paths, and add acceptance tests that distinguish “BFCache fixed” from “all return paths fixed.”

### F5.3 — Repeating the same maneuver with two different live distances invites ambiguity
Severity: SHOULD-FIX
Claim: Issue 2 makes both far-tier and near-tier speak a live distance for the same maneuver, e.g. “In 1/4 mile, turn right onto X” followed 15 seconds later by “In 200 feet, turn right onto X.” That is standard-sounding navigation language, but the spec never states which utterance is meant to be operative when they disagree. The current design goal is “prefix every prompt,” not “make escalation semantics unmistakable.”
Impact: Drivers can interpret the second prompt as a correction to the first rather than an expected escalation, especially when GPS jitter or speed variation changes the bucket unexpectedly near a boundary. The ambiguity gets worse because the street name is identical and the spec intentionally preserves prompt count.
Recommendation: Add a new requirement in section 5 that the near-tier for a maneuver already announced at far-tier must use an explicitly-imminent form instead of a second ordinary distance readout. Example spec edit: “If the same maneuver’s far-tier has already fired, near-tier text MUST use an imminent cue (`Now, turn right onto X` or unprefixed `Turn right onto X`) rather than another `In <distance>` prefix.” Add an integration test that asserts same-maneuver far/near pairs are distinguishable by wording, not only by distance bucket.

### F5.4 — GPS-dropout recovery semantics are underspecified and can produce a jarring post-recovery prompt
Severity: MUST-FIX
Claim: TTM v3 G11 explicitly keeps dead reckoning position-only, so `checkVoice()` does not run during GPS dropout. This follow-up spec adds live-distance prefixes but never defines what happens on the first recovered GPS tick after stale time. That recovered tick can jump from the driver’s mental estimate to a suddenly-accurate `distToNext`, causing a far-tier or near-tier to speak a sharply different prefix from what the driver expected, with no stale/recovery guard.
Impact: The first prompt after GPS recovery can sound wrong or late: a driver who mentally expects “about a quarter mile” may suddenly hear “In 200 feet,” or vice versa, because the engine was silent throughout dropout and then resumes with a single precise snapshot. That is a real UX discontinuity introduced by combining G11 with Issue 2’s stronger distance wording.
Recommendation: Add a recovery rule in sections 2 and 5: on the first fresh GPS tick after `gpsStale === true`, either suppress far-tier entirely and allow only near-tier/imminent speech, or suppress the live-distance prefix for one tick and speak only the maneuver text. Add an engine test that simulates stale GPS, dead reckoning progression, GPS recovery near a maneuver, and asserts the recovered prompt is intentionally constrained rather than whatever bucket the first recovered distance happens to land in.

### F5.5 — The test plan misses the full `stripBakedDistance` + `Then` interaction
Severity: SHOULD-FIX
Claim: Section 5.5 tests `stripBakedDistance()` in isolation and tests chain behavior in isolation, but it never tests the full near-tier pipeline order that section 5.2 says is load-bearing. For `In 400 feet, Turn right. Then Turn left.`, the spec’s intended final text is `In 400 feet, turn right.`: first strip trailing `Then`, then strip baked distance, then uppercase-normalize, then prepend the live prefix. That exact pipeline is not pinned anywhere.
Impact: A future implementation can reorder those transforms and still satisfy the listed unit tests while regressing the real utterance shape, producing double distance cues, leaving the trailing `Then` clause intact, or lowercasing incorrectly after prepend.
Recommendation: Add an explicit integration test in section 5.5: `verbal_pre_transition_instruction = "In 400 feet, Turn right. Then Turn left."` with `distToNext` in the 400-foot band must yield exactly `In 400 feet, turn right.` Also add one negative control where the live distance differs from the baked distance to prove the output is driven by the live snapshot, not by preserved source text.

### F5.6 — The regex concern is misframed: catastrophic backtracking is unlikely, but semantic drift is the real risk
Severity: NICE-TO-HAVE
Claim: Section 9 asks reviewers to stress catastrophic backtracking on `BAKED_DISTANCE_RE`, but this pattern does not show the usual ReDoS shape: it is anchored, has one lazy quantified middle, and has no nested ambiguous quantifiers. The bigger risk is semantic mismatch, not exponential runtime: unusual Valhalla prefixes such as “In about half a mile” or lowercase residual text will fail to strip and can produce duplicate-distance speech even though the regex is fast.
Impact: Review attention gets spent on the wrong failure mode. The team may conclude the regex is “safe” after a backtracking pass while missing the more plausible production failure, which is incorrect stripping coverage.
Recommendation: Edit section 5.1 or 9 to say explicitly that catastrophic backtracking is not the expected risk class here, then add coverage tests for wording variants instead: `about half a mile`, `three quarters of a mile`, lowercase residual text, and mixed-unit abbreviations. If the implementation stays regex-based, add a short rationale comment documenting why ReDoS is not a concern for this specific pattern.

### F5.7 — Restoring the tab via synthetic `.click()` can interfere with active form focus on return
Severity: SHOULD-FIX
Claim: Section 6 relies on `targetTab.click()` because it preserves existing tab side effects, but the spec does not analyze focus and form-state fallout. If the user backgrounds while editing `#route-start` or `#route-end` in the Route panel and returns through a lifecycle path where the visible tab state has drifted back to Layers, the synthetic click will blur the active input, collapse text selection, and may trigger any blur-driven validation or route-regeneration behavior attached elsewhere.
Impact: The sidebar can “restore correctly” while still degrading the active task the user was in the middle of. This is especially plausible for the exact field scenario under discussion: active navigation with the Route tab open.
Recommendation: Amend section 6.2 to preserve focus-sensitive state during restore. Preferred spec edit: replace the synthetic click with a dedicated `setActiveSidebarTab(panelId, { preserveFocus: true })` helper that mirrors the class toggles and only invokes special side effects explicitly needed for Admin. Minimum: gate the `click()` path when `document.activeElement` is an editable control inside a non-target panel, or capture/restore focus and selection around the tab restore. Add an acceptance check for “typing in route-start, background, return” and assert the input value, focus, and selection survive.

Summary count: 2 MUST-FIX, 4 SHOULD-FIX, 1 NICE-TO-HAVE.

exec
/bin/bash -lc "grep -RInE \"F5\\.3|F5\\.7|ambigu|synthetic \\.click|blur active form input|same maneuver with two different live distances|BFCache\" dev/adversarial/2026-04-24-nav-voice-followup-r*.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:6:**Attack angle:** API / correctness — edit recipe bugs, invariant violations, semantic drift in `checkVoice`, order-of-operations, exception safety, BFCache idempotency under realistic event sequences.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:116:So the spec IS using the topological (M5-to-M6) interpretation for §5.4, but the annotation "M6 @ 117 m" is ambiguous — does 117 m mean distance-from-driver or distance-from-M5?
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:197:### F1.6 — BFCache restore before DOMContentLoaded: idempotency claim holds, but `initSidebarTabs()` click handlers must be attached before the `pageshow` listener's `.click()` fires, and the spec's "module-scope" placement does not enforce this ordering
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:209:Per the HTML spec, `pageshow` fires after page-load event (after DOMContentLoaded + window.load). So this sequence shouldn't happen on a fresh load. BUT on BFCache-restore, the page has ALREADY fully loaded previously. BFCache fires `pageshow` with persisted=true without running DOMContentLoaded again. However, BFCache ALSO preserves the previously-registered event listeners, so the click handlers wired by `initSidebarTabs()` on the first-ever load are still live.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:211:This is fine for the normal case. But consider a subtle failure mode: if the first load NEVER completed `initSidebarTabs()` (e.g., a prior script threw and broke the bootstrap, but the browser still BFCached the partially-initialized page), pageshow.persisted=true fires, `restoreLastSidebarTab()` runs, finds `targetTab`, does `.click()` — which dispatches a click event but NO handler is attached. The click has no effect. User is on wrong tab, no error.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:217:**Impact:** Low-probability correctness hit on BFCache restores after a broken first-load. Higher-probability is a future refactor moving the pageshow listener to global scope and breaking the reference to `restoreLastSidebarTab`.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:221:> Place the pageshow listener at the END of the DOMContentLoaded callback, AFTER `restoreLastSidebarTab()` has fired once synchronously. This ensures all click handlers are wired before any future BFCache restore can invoke `restoreLastSidebarTab()` via the pageshow path. The first-load tab restoration comes from the DOMContentLoaded call; BFCache restorations thereafter come from the listener.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:242:### F1.7 — Admin-tab polling timer leaks on BFCache restore when the polling tab WAS admin before backgrounding
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:250:Consider: user is on Admin tab when the app backgrounds. BFCache preserves the running `setInterval` (adminTimer). Resume via BFCache: pageshow.persisted=true fires. `restoreLastSidebarTab` reads localStorage `'admin-panel'`, finds Admin button, checks `!classList.contains('active')` → FALSE (BFCache preserved the active state). Early-returns. adminTimer continues running. ✓ Good.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:252:Now consider: user is on Admin when backgrounded. BFCache restore fires pageshow.persisted=true. But between backgrounding and resume, iOS background-throttling killed the setInterval callback. When BFCache restores, setInterval is... per spec, BFCached timers resume on restore (Chromium v88+, Safari 15+). So timer continues firing post-restore.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:254:BUT: what if BFCache restored state is different from user-intended? E.g., user was on Route tab, backgrounded (adminTimer=null, Route active in DOM). App evicted from BFCache, full reload fires DOMContentLoaded. Static HTML has Layers active. `restoreLastSidebarTab` finds localStorage='route-panel', calls Route.click() → initSidebarTabs handler runs, Route becomes active. Route's click handler (in initAdmin's other-tabs registration) clears adminTimer (was already null, no-op). ✓
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:260:But the REAL bug is subtler. Spec §6.2 places the pageshow listener OUTSIDE DOMContentLoaded. If a BFCache restore fires before `initAdmin()` has ever run (impossible for BFCache because BFCache implies prior complete load, but let's consider unloaded-prefetch)... actually this is fine.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:262:Hmm let me look for a real issue. Consider: user is on Admin when backgrounded. iOS aggressively evicts from BFCache (memory pressure). User returns; browser does NOT BFCache-restore (evicted); full reload. DOMContentLoaded fires, static HTML has Layers active. `initAdmin()` wires handlers. `restoreLastSidebarTab()` reads localStorage='admin-panel', clicks Admin tab → initSidebarTabs handler activates Admin panel. initAdmin handler fires `fetchAdminStatus(); clearInterval(null); adminTimer = setInterval(...)`. ✓
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:264:Now consider: BFCache restores and the Admin tab was NOT previously active (user was on Route). Spec §6.2 pageshow listener fires, calls `restoreLastSidebarTab()`. localStorage='route-panel' (matching what DOM already shows). `!targetTab.classList.contains('active')` = FALSE → early-return. adminTimer remains null. ✓
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:266:Now the SPECIFIC BUG: user was on Admin, backgrounded, BFCache restores and admin timer was already running. pageshow fires. `restoreLastSidebarTab` sees Admin already active → early-returns. adminTimer keeps running. Good.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:268:But wait — what if Admin is in localStorage but NOT active in DOM post-BFCache-restore? This requires BFCache to NOT preserve the .active class, which contradicts the whole BFCache model. UNLESS the page was evicted and fully reloaded — but then pageshow.persisted would be FALSE, not true, and the listener early-returns via `e.persisted`.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:272:BUT — here's the gotcha: `restoreLastSidebarTab` only early-returns when the target tab is already active. What if both target tab and current tab are Admin, and `adminTimer` is nevertheless NULL (because iOS terminated the BFCached interval)? Then the Admin tab is visually active but no polling is running. pageshow fires → restoreLastSidebarTab checks active → TRUE → early-returns → polling stays DEAD. The user sees Admin tab active but the service status never refreshes.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:274:This is an existing bug UNRELATED to this spec, but the spec's pageshow path doesn't fix it — and the spec claims "reopening the sidebar after any iOS Safari BFCache restore-event produces the tab that was active before the backgrounding, matching the user expectation" (G9). User expectation might be stronger: "the tab AND its live data." If Admin polling is dead post-BFCache, G9 is weakly satisfied.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:276:**Impact:** On Admin tab specifically, BFCache restore may leave the tab cosmetically correct but with dead polling. User sees stale status. Low severity for non-active-users; confusing for Cameron if he tries to monitor a running data pipeline from a backgrounded-then-restored app.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:284:    // iOS may kill BFCached setIntervals. Re-wake admin polling if admin is active.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:294:But `activeTab.click()` when already-active triggers the initSidebarTabs handler again (no-op since already active), AND the initAdmin handler (restarts polling). Verify with a manual iOS BFCache test.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:296:Alternatively, split the concern into a separate issue and only ship the bare BFCache fix now with a TODO noting the adminTimer-BFCache-eviction case for a future patch. Spec §6.4 should document the limitation.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:418:This is a MUST-FIX because an ambiguous test vector will cause a test failure that blocks ship.
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:458:- **MUST-FIX: 1** (F1.10 — 1000 ft band-boundary test vector ambiguity blocks ship)
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:459:- **SHOULD-FIX: 6** (F1.1 empty-text chain leading-comma; F1.2 prefix throw infinite-retry; F1.3 Issue-2 prefix cost eats Issue-1 buffer; F1.4 distBetween semantics ambiguous in §5.4 annotation; F1.5 decimal-mile chain strip miss; F1.6 pageshow-before-DOMContentLoaded init ordering; F1.7 admin polling stays dead after BFCache timer eviction)
dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md:464:F1.6 and F1.7 deserve consideration together: the BFCache path has three distinct sub-cases (persisted + DOM-synced, persisted + DOM-desynced, non-persisted) and §6.2-6.4 elide them. A brief sub-case table in §6 would close the ambiguity.
dev/adversarial/2026-04-24-nav-voice-followup-r3-numerical.md:177:- **iOS Safari (Siri voices)** typically pronounce `"1/4"` as `"one quarter"` when adjacent to a unit noun, but standalone `"1/4"` can be read as `"January 4"` (date heuristic) or `"one-fourth"`. With `"1/4 mile"` the unit disambiguates, but this is undocumented.
dev/adversarial/2026-04-24-nav-voice-followup-r3-numerical.md:186:1. Change the imperial strings to spelled-out fractions to eliminate the risk: `"In a quarter mile, "`, `"In a third of a mile, "`, `"In a half mile, "`, `"In three quarters of a mile, "`, `"In 1 mile, "`. Every TTS engine pronounces these unambiguously.
dev/adversarial/2026-04-24-nav-voice-followup-r3-numerical.md:246:### F3.N-10 — 100 m cutoff rule ambiguity at the boundary
dev/adversarial/2026-04-24-nav-voice-followup-r3-numerical.md:263:**Impact.** Ambiguity risk: an implementer might code `m < 100` for one branch and `m < 100` again for the other, creating an unreachable case. Trivial to catch in review, but spec should be unambiguous.
dev/adversarial/2026-04-24-nav-voice-followup-r3-numerical.md:358:### F3.N-15 — Cutoff of `""` (no prefix) breaks the §5.1 return-type contract ambiguity with falsy checks
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:6:**Attack angle:** Does the spec actually solve Cameron's field problem? Does it introduce new UX regressions (speech overruns, chopped audio, information overload, parity drift)? Does the sidebar fix honor user intent on BFCache restore?
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:60:(c) **Stop prefixing the chain-append's distance.** "Turn left onto 21st, then turn left onto Union Hills" (14 syllables). Drops 6 syllables = ~1.5 s of speech at the cost of losing the secondary-maneuver distance. Cameron's Issue 2 motivation was "driver with eyes-on-road can't disambiguate" — but the chain-append's "then" already signals relative imminence, and the primary prefix already sets up the interval. Parse the cost/benefit and commit.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:136:- **Far-tier:** always prefix (this is the whole point of Issue 2 — resolves the "turn right" ambiguity at 486 m).
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:140:This delivers Issue 2's primary value (disambiguating far-tier turns), retains eyes-free clarity on near/imminent turns, and buys back ~0.8 s of post-speech buffer on the near-tier — closing F4.1's net-improvement shortfall without lifting the floor further.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:164:### F4.8 — BFCache `pageshow` handler may race restoreLastSidebarTab() with in-progress sidebar-tab click, causing visible flicker
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:172:4. User returns 30 min later. BFCache restore fires `pageshow(persisted=true)`. New handler calls `restoreLastSidebarTab()`.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:175:Case 5b (BFCache snapshot captured class state post-DOM-commit, but our localStorage says the same tab should be active) is the normal path and is harmless.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:177:Case 5c (BFCache snapshot captured pre-DOM-commit, so tab DOM looks like Layers but localStorage says Route): `targetTab.click()` correctly fires, restoring Route. But it goes through the FULL click handler including `initAdmin`-polling-start semantics (comment at `app.js:4115`). If `admin-panel` was the target, this starts admin polling. Benign, intentional per the comment.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:179:**BUT** — consider this adversarial case: user is on Layers. They click Route. Between `localStorage.setItem` (line 1161) and the next paint, iOS backgrounds. They return; BFCache restores the page DOM state as it was *at backgrounding* (which may be mid-frame — Route tab button class has `.active`, Route panel has `.active`). The listener fires `restoreLastSidebarTab`, sees Route already active, early-returns. Result: no restore needed, no flicker. Good.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:181:So the BFCache race is actually fine in practice. But the spec doesn't discuss this sequence — it assumes BFCache always restores the PRE-click state. On iOS Safari the behavior is complex and not fully documented.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:183:**Impact:** Low risk of flicker; the idempotency guard at `app.js:4113` handles all the cases I can trace. But the spec's invariant G10 ("normal pageshow events are no-ops") is stronger than what's actually provable — a `pageshow` with `persisted=true` that arrives right after a DOMContentLoaded-triggered restore is NOT a no-op if the BFCache snapshot has stale tab state.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:185:**Recommendation:** Tighten G10's language to "idempotent, not no-op." Add a comment inside the `pageshow` listener noting that the DOMContentLoaded path and pageshow path can both fire for a single page load in rare iOS cases (cold start that gets BFCache-backgrounded before first paint), and both calls converge on the same DOM state. No code change needed; documentation only.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:233:### F4.11 — Sidebar BFCache fix trace: user's LATEST choice IS respected; but add a regression guard test
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:242:3. User backgrounds app. BFCache captures state with Layers active.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:243:4. User returns. `pageshow(persisted=true)` fires. `restoreLastSidebarTab` reads localStorage → `layers-panel`. Checks if Layers is active → YES (BFCache preserved it) → early-return.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:247:The only case that goes wrong is if localStorage and BFCache-DOM are out of sync (step 5c in F4.8), and in that case `targetTab.click()` restores from localStorage, which IS the user's last explicit click. So localStorage is authoritative, and that's correct.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:251:**Recommendation:** Add to §6.3 structural test (or better, a JS unit test if the bootstrap test runner supports DOM): simulate the sequence (user clicks Route, then Layers, then we simulate BFCache restore by manually manipulating `.active` classes and invoking the listener). Assert that `restoreLastSidebarTab` converges on the localStorage value regardless of DOM state. This is a logic-invariant test, not an integration test — cheap to write, guards against future regression of the precedence rule.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:288:- Issue 3 (sidebar BFCache) is a 10-line fix, orthogonal to nav, field-verifiable in 30 seconds.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:298:- **PR 1:** Issue 3 (sidebar BFCache). 30-minute review, ships immediately, closes a user-visible iOS defect.
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:311:- **NICE-TO-HAVE: 3** (F4.5 "then in"/"than in" homophone; F4.8 pageshow-DOM-race documentation; F4.10 pedestrian prefix feels premature; F4.11 BFCache last-click test guard — correction: this is 4, making 3 NICE + 1 additional guard-test suggestion)
dev/adversarial/2026-04-24-nav-voice-followup-r4-product.md:325:The Sidebar BFCache fix (Issue 3) is independently correct and should ship; F4.13 recommends separating it from the voice work to de-risk its rollout.
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:7:### F5.2 — The BFCache diagnosis is overstated and the proposed listener does not cover the full iOS return path
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:9:Claim: Section 6 treats BFCache as the primary cause and section 6.4 claims the `pageshow` listener gives “full cover over all page-lifecycle events.” That is too strong. `pageshow` with `persisted === true` only covers one return mode. Similar “sidebar reverted to default tab” symptoms can also come from `pageshow` with `persisted === false` after a tab discard or renderer recreation, standalone-PWA process recreation, `visibilitychange`/resume paths that partially rehydrate UI without rerunning the original restore point, or an interruption path where speech/audio/session code mutates visible state while the page returns. None of those are fixed by the proposed guard.
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:10:Impact: The PR can ship with a satisfying BFCache narrative while leaving the user-visible bug reproducible on other iOS Safari return paths. If that happens, the team will think the lifecycle bug is closed when it is only narrowed.
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:13:- Minimum: add explicit non-goals for `persisted === false`, standalone-PWA recreation, and tab-discard paths, and add acceptance tests that distinguish “BFCache fixed” from “all return paths fixed.”
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:15:### F5.3 — Repeating the same maneuver with two different live distances invites ambiguity
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:18:Impact: Drivers can interpret the second prompt as a correction to the first rather than an expected escalation, especially when GPS jitter or speed variation changes the bucket unexpectedly near a boundary. The ambiguity gets worse because the street name is identical and the spec intentionally preserves prompt count.
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:35:Claim: Section 9 asks reviewers to stress catastrophic backtracking on `BAKED_DISTANCE_RE`, but this pattern does not show the usual ReDoS shape: it is anchored, has one lazy quantified middle, and has no nested ambiguous quantifiers. The bigger risk is semantic mismatch, not exponential runtime: unusual Valhalla prefixes such as “In about half a mile” or lowercase residual text will fail to strip and can produce duplicate-distance speech even though the regex is fast.
dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:39:### F5.7 — Restoring the tab via synthetic `.click()` can interfere with active form focus on return

exec
/bin/bash -lc "sed -n '1,220p' dev/adversarial/2026-04-24-nav-voice-followup-r1-api-correctness.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
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


codex
I’ve confirmed one concrete defensibility problem in the draft itself: at least one cycle-5 row is labeled `CLAUDE-EXCLUSIVE` while citing a Codex review file as the source of the finding. That doesn’t invalidate the whole thesis, but it does mean the document is not clean enough yet for a hostile audience.
exec
/bin/bash -lc "nl -ba dev/notes/cross-model-review-value-draft-v1.md | sed -n '1,260p'" in /home/administrator/Code/geographica
 succeeded in 0ms:
     1	# Cross-model adversarial review — quantified value
     2	
     3	> Pitch-ready ROI analysis for adopting cross-model adversarial review on
     4	> top of existing single-model coding-assistant infrastructure.
     5	>
     6	> Prepared: 2026-04-25 · Agent: gravel · Source data: dev/adversarial/ (40 files)
     7	
     8	---
     9	
    10	## TL;DR for decision-makers
    11	
    12	- Across 8 distinct review cycles covering navigation, voice, measurement, and cost methodology, the cross-model harness surfaced **41 exclusively model-specific critical findings** — 16 caught only by Codex (OpenAI) and 25 caught only by Claude rounds — that the other model did not surface.
    13	- Using conservative bug-cost rubric (NIST SP 500-235 / IBM Systems Sciences Institute, 2002), exclusive-catch findings represent **$297,600 in avoided downstream work** that single-model review would have missed.
    14	- The harness costs **$2,640/yr** per developer (Claude Max + ChatGPT Plus). The avoided-cost ROI is **~113× annual subscription cost**.
    15	- The pitch does not rest on "Claude vs. OpenAI." Both models are capable. The evidence shows each model's architecture creates predictable blind spots that the other consistently fills — the value is in the *combination*, not the individual models.
    16	- Top Codex-exclusive catches: (1) cost-methodology pricing constants wrong by 3× (output token double-count compounds to 5.6× inflation); (2) editing-state click leakage into reverse-geocode handler; (3) spec-wide internal inconsistency — NoSleep architecture still embedded after R1-R5 invalidated it. Top Claude-exclusive catches: (1) cache-write exclusion unjustified by the methodology's own standard (framing hole); (2) `ccusage` cited as validation but cannot validate itself; (3) negative `distanceToManeuver` returns pass every TTM threshold.
    17	
    18	---
    19	
    20	## Methodology
    21	
    22	### Rubric basis
    23	
    24	Bug-cost multipliers follow the NIST Special Publication 500-235 (2002), "The Economic Impacts of Inadequate Infrastructure for Software Testing," and the IBM Systems Sciences Institute study (cited in that publication) that established the canonical bug-cost-by-phase curve:
    25	
    26	- A defect found during design/spec review costs **~1× engineer-day** to fix.
    27	- The same defect found in integration testing costs **~6–10×** more.
    28	- The same defect reaching production costs **~30–100×** more, due to triage, hotfix deployment, communication, and data remediation.
    29	
    30	Source: Capers Jones, *Software Quality: Analysis and Guidelines for Success* (1997), cross-referenced in NIST SP 500-235 §5.3. The IBM SSI paper is widely republished as "the cost to fix a bug grows 5x-10x per phase"; the NIST survey anchors the 30× production multiplier.
    31	
    32	This analysis uses the **conservative end** of every range. No finding is assigned the 100× multiplier; CRITICALs shipped to production are capped at 30×.
    33	
    34	### Cost rubric (all figures in USD)
    35	
    36	```
    37	Avoided cost = severity_multiplier × loaded_engineer_hours × $120/hr
    38	
    39	severity_multiplier:
    40	  CRITICAL bug caught at spec review:       1×   (finding in review prevents the multiplier)
    41	  MAJOR bug caught at spec review:          1×
    42	  CRITICAL bug that would ship:            30×   (NIST production multiplier)
    43	  MAJOR bug that would ship:                5×
    44	
    45	loaded_engineer_hours per category:
    46	  Math / calculation / pricing error:       8h
    47	  Framing / documentation bug:              4h
    48	  API / behavioral correctness:            12h
    49	  Concurrency / race condition:            16h
    50	  Data integrity / security:               24h
    51	  Spec internal inconsistency:              6h   (misleads implementer, causes rework)
    52	```
    53	
    54	The $120/hr rate is conservative for a senior engineer, fully loaded (benefits, overhead, opportunity cost). Industry median in 2025 for a software engineer is $80–$160/hr depending on market; $120 is the geometric mean of that range.
    55	
    56	### Attribution rules
    57	
    58	A finding is classified:
    59	
    60	- **CODEX-EXCLUSIVE** if it appears in the Codex round (R5 or R6) and is absent from all parallel Claude rounds for that cycle.
    61	- **CLAUDE-EXCLUSIVE** if it appears in ≥1 Claude round and is absent from the Codex round.
    62	- **CROSS-CONFIRMED** if caught independently by both model families (same finding identified without one influencing the other).
    63	- **CONSENSUS** if caught by all reviewers regardless of model.
    64	
    65	When in doubt, the conservative classification is used (CROSS-CONFIRMED over CODEX- or CLAUDE-EXCLUSIVE).
    66	
    67	Rounds R1–R4 (all Claude) are the "Claude side." Rounds R5–R6 are "Codex side" (Codex CLI via OpenAI gpt-5.4 / ChatGPT-auth mode).
    68	
    69	---
    70	
    71	## The catch inventory
    72	
    73	### Cycle 1: Cost methodology (2026-04-25)
    74	
    75	**Reviewers:** R1 (Claude/wren), R2 (Claude/basalt), R3 (Claude/flint), R5 (Codex)  
    76	**Note:** R1, R2, and R5 are classified separately despite addressing overlapping topics, because they ran independently. R1 is primarily a math/pricing lens, R2 a coverage/sampling lens, R5 a cross-model pricing verification lens.
    77	
    78	| ID | Severity | Exclusivity | Avoided cost | Description |
    79	|----|----------|-------------|-------------|-------------|
    80	| CM-C1a | CRITICAL | CODEX-EXCLUSIVE | $28,800 | Opus 4.x pricing constants wrong by 3×: $15/$75 vs correct $5/$25; Codex independently fetched Anthropic pricing docs and verified against LiteLLM DB. Claude rounds (R1, R2) confirmed after-the-fact that they had _not_ cross-checked against a live source before Codex did. R5 is the first file to cite a specific dollar-verified cross-check using ccusage token counts. *File: 2026-04-25-cost-methodology-r5-codex.md* |
    81	| CM-C1b | CRITICAL | CROSS-CONFIRMED | — | Same pricing error (R1 and R2 both caught it; R1 cites Anthropic docs, R2 cites LiteLLM). Classified CROSS-CONFIRMED; not counted in exclusive ROI. |
    82	| CM-C2 | CRITICAL | CODEX-EXCLUSIVE | $28,800 | Output tokens double-counted due to streaming partial records; dedup by message.id required; net inflation 5.6× compound with C1. Codex identified via transcript-format analysis from an OpenAI-transcript-protocol perspective; Claude R1/R2/R3 did not surface this. *File: 2026-04-25-cost-methodology-r5-codex.md* |
    83	| CM-C3 | CRITICAL | CLAUDE-EXCLUSIVE | $5,760 | Cache-write exclusion from headline is unexplained; by the methodology's own standard, cache writes are billable compute work and should be in the headline. Hostile-reader framing. *File: 2026-04-25-cost-methodology-r3-framing.md (C1)* |
    84	| CM-C4 | CRITICAL | CLAUDE-EXCLUSIVE | $5,760 | "Matches ccusage" is appeal-to-tool, not appeal to billing truth; ccusage cannot independently validate numbers it contributed to computing. *File: 2026-04-25-cost-methodology-r3-framing.md (C2)* |
    85	| CM-C5 | CRITICAL | CLAUDE-EXCLUSIVE | $5,760 | Cache-reads-as-harness-artifact is asserted without argument; a hostile reader can rebut it immediately; three sub-objections enumerated. *File: 2026-04-25-cost-methodology-r3-framing.md (C3)* |
    86	| CM-M1 | MAJOR | CROSS-CONFIRMED | — | `model_tier()` too coarse; mixed-generation corpora mis-priced. Both R1 and R2 flagged. |
    87	| CM-M2 | MAJOR | CLAUDE-EXCLUSIVE | $3,840 | Codex usage (30 sessions, gpt-5.4) documented in `~/.codex/sessions/` is real but absent from methodology disclosure; creates a reproducibility gap. *File: 2026-04-25-cost-methodology-r2-coverage.md (M1)* |
    88	| CM-M3 | MAJOR | CROSS-CONFIRMED | — | Spec's stated dollar figures ($2,489/$21,858) do not match script output at any pricing assumption; both R1 and R2 flagged. |
    89	| CM-M4 | MAJOR | CLAUDE-EXCLUSIVE | $3,840 | "Anyone can reproduce" overstates reproducibility — only Cameron can run the script against his private transcript directory; external auditors cannot. *File: 2026-04-25-cost-methodology-r3-framing.md (M3)* |
    90	
    91	**Cycle 1 subtotals:**
    92	- CODEX-EXCLUSIVE: 2 CRITICAL → $57,600
    93	- CLAUDE-EXCLUSIVE: 3 CRITICAL + 2 MAJOR → $24,960
    94	- CROSS-CONFIRMED/CONSENSUS: not counted in exclusive ROI
    95	
    96	---
    97	
    98	### Cycle 2: Ruler/measurement tool (2026-04-24)
    99	
   100	**Reviewers:** R1 (Claude/cholla), R2 (Claude/cholla), R3 (Claude/cholla), R4 (Claude/cholla), R5 (Codex)
   101	
   102	| ID | Severity | Exclusivity | Avoided cost | Description |
   103	|----|----------|-------------|-------------|-------------|
   104	| RL-C1 | CRITICAL | CONSENSUS | — | Terrain-RGB decode formula wrong (Mapbox vs Terrarium); caught independently by R1, R2, and R4 before Codex ran. All Claude rounds caught it. |
   105	| RL-C2 | CRITICAL | CONSENSUS | — | `useImperial` closure snapshot produces stale unit after toggle; caught by R1 and R4. |
   106	| RL-C3 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | Editing-state vertex clicks leak into reverse-geocode handler: `isActive()` returns false in `editing` state, so the app.js L1622 suppression does not fire; every vertex-select tap also opens a reverse-geocode popup. R1-R4 each caught the `isActive()` boundary but none independently identified this specific leakage path. Codex traced the actual `queryRenderedFeatures` exclusion list at L1622-1635 and found ruler layers were absent. *File: 2026-04-24-ruler-r5-codex.md (C1)* |
   107	| RL-M1 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Style-load reattach pattern doesn't match cited precedent; layer-ordering race with `_enforceImageryOrder()`; R1 traced the MapLibre listener insertion-order semantics. *File: 2026-04-24-ruler-r1-architectural.md* |
   108	| RL-M2 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Missing `text-font` declaration in `ruler-vertex-labels` symbol layer; offline tileserver only serves Metropolis+Noto; labels render blank. R1 traced `tileserver/fonts-served/` directory. *File: 2026-04-24-ruler-r1-architectural.md* |
   109	| RL-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Bootstrap ordering: `initRuler()` must run after `initSidebarTabs()` and before `restoreLastSidebarTab()` — specific sequence not specified; race causes `clear()` not to fire on persisted-tab restoration. *File: 2026-04-24-ruler-r1-architectural.md* |
   110	| RL-M4 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Index panel class naming drift: spec says `class="sidebar-panel hidden"` but codebase uses `class="panel"` + `.active`; spec implementation would be invisible regardless of state. *File: 2026-04-24-ruler-r1-architectural.md* |
   111	| RL-M5 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Tile cache decoded-pixel size understated (192KB/tile claimed, actual is 256KB RGBA); ImageBitmap retention doubles worst-case memory; no LRU eviction policy → unbounded session growth. *File: 2026-04-24-ruler-r2-scale-performance.md (F2.4, F2.9)* |
   112	| RL-M6 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | z=12 sample zoom claims "~9.5 m/px at AZ latitude" — actual is ~32 m/px; error is 3.4×; invalidates 50-tile cap rationale, sample spacing logic, and the entire "Why z=12" justification. *File: 2026-04-24-ruler-r2-scale-performance.md (F2.2)* |
   113	| RL-M7 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Vertex hit targets (16px diameter) fail WCAG 2.5.5 and Apple HIG 44px minimum; invisible 44px hit-area layer not specified; feature is demonstrably unusable with gloves. *File: 2026-04-24-ruler-r3-ux-mobile-a11y.md (CRITICAL-1)* |
   114	| RL-M8 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | `#ruler-mode-banner` collides physically with `#nav-banner` (full-width, z-index 18); nav-active + ruler-active is a real workflow; spec defers without resolution. *File: 2026-04-24-ruler-r3-ux-mobile-a11y.md (CRITICAL-3)* |
   115	| RL-M9 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Font stack wrong relative to actual style corpus: spec says `['Metropolis Regular']` but all three shipped basemap styles use `['Metropolis Regular', 'Noto Sans Regular']`; brittle glyph fallback. R1 had partially caught this (same finding root), but Codex traced all three tileserver style files independently. *File: 2026-04-24-ruler-r5-codex.md (M3)* |
   116	| RL-M10 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Terrarium decode guard missing: `(0,0,0)` decodes to −32,768 m and will dominate min/max/gain; spec says "compute on non-null samples" but never defines when a sample is null; R1-R4 noted the formula fix but none added the sentinel guard. *File: 2026-04-24-ruler-r5-codex.md (M4)* |
   117	| RL-M11 | MAJOR | CODEX-EXCLUSIVE | $5,760 | app.js integration insert-count claimed as "5 inserts + 1 whitelist edit" but the `addPlaceholderSources()` style-load hook is a 6th edit not in the count; also, editing-state click fix (C3) adds another; scope misrepresented, merge-risk analysis wrong. *File: 2026-04-24-ruler-r5-codex.md (M2)* |
   118	
   119	**Cycle 2 subtotals:**
   120	- CODEX-EXCLUSIVE: 1 CRITICAL + 3 MAJOR → $60,480
   121	- CLAUDE-EXCLUSIVE: 8 MAJOR → $46,080
   122	- CONSENSUS/CROSS-CONFIRMED (C1, C2): not counted
   123	
   124	---
   125	
   126	### Cycle 3: Nav-voice TTM redesign (2026-04-20)
   127	
   128	**Reviewers:** R1 (Claude), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Claude/product), R6 (Codex)
   129	
   130	| ID | Severity | Exclusivity | Avoided cost | Description |
   131	|----|----------|-------------|-------------|-------------|
   132	| TTM-C1 | CRITICAL | CLAUDE-EXCLUSIVE | $43,200 | `distanceToManeuver` returns signed values; negative TTM passes every threshold; far-tier fires for already-executed maneuvers. R6 (Codex) did not surface this specific arithmetic hazard. *File: 2026-04-20-nav-voice-ttm-r1-api-correctness.md (F1.1)* |
   133	| TTM-C2 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | `start()` does not run the TTM pipeline on activation; G2 and G4 spec guarantees ("1 prompt per maneuver at route-start") are structurally false because `checkVoice()` is never called on start; `currentManeuverIdx` left at 0 on mid-route start → wrong next-maneuver announced. Claude R1-R5 focused on `tick()` path exclusively. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.1)* |
   134	| TTM-C3 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | "No nav-ui changes" spec claim (NG3/G9) becomes structurally false if start-time voice is implemented to satisfy G2/G4: first prompt fires before mute-sync and before speech priming, because `nav-ui.js:154-161` initializes mute after `nav.start()`. Both guarantees cannot simultaneously be true in the existing architecture. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.2)* |
   135	| TTM-M1 | MAJOR | CODEX-EXCLUSIVE | $5,760 | "3-maneuver route → 3 spoken prompts" test is off by one: engine voices the **upcoming** maneuver; a 3-maneuver route produces at most 2 spoken prompts under current semantics. Claude rounds wrote tests that would validate against the wrong maneuver semantics. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.3)* |
   136	| TTM-M2 | MAJOR | CODEX-EXCLUSIVE | $5,760 | G7 "behavior is deterministic" is false: `tick()` uses `Date.now()` repeatedly; stale-GPS voice is generated by a 1Hz interval; `updateGPS()` stamps `lastGPSTime = Date.now()` not the GPS timestamp field. Same route+GPS sequence with different inter-arrival timing produces different voice output. *File: 2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md (F6.4)* |
   137	
   138	**Cycle 3 subtotals:**
   139	- CODEX-EXCLUSIVE: 2 CRITICAL + 3 MAJOR → $103,680
   140	- CLAUDE-EXCLUSIVE: 1 CRITICAL → $43,200
   141	
   142	---
   143	
   144	### Cycle 4: Nav wake-lock / keep-awake (2026-04-20)
   145	
   146	**Reviewers:** R1 (Claude), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Claude/product), R6 (Codex)
   147	
   148	| ID | Severity | Exclusivity | Avoided cost | Description |
   149	|----|----------|-------------|-------------|-------------|
   150	| WL-C1 | CRITICAL | CODEX-EXCLUSIVE | $14,400 | Spec is structurally inconsistent: R1 invalidated NoSleep.js architecture but the spec still names `frontend/vendor/nosleep.min.js`, `window.NoSleep`, NoSleep-specific tests, and the appendix justifying NoSleep v0.12.0. A subagent following the written spec would reintroduce the rejected dependency. No prior Claude round synthesized across all spec sections to catch this whole-spec inconsistency. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.1)* |
   151	| WL-C2 | CRITICAL | CODEX-EXCLUSIVE | $14,400 | "Silent video" helper is underspecified: an MP4 with an audio track of silence (vs no audio track at all) interacts differently with autoplay policy, media sessions, and the co-active `speechSynthesis` + `getUserMedia` APIs. On iPhone-in-vehicle, the wrong spec causes the fallback to require stricter user activation than expected. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.4)* |
   152	| WL-M1 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Bespoke HTTP fallback needs CSP/Permissions-Policy contract: `blob:` or `data:` media requires explicit `media-src` allowance; future security hardening silently breaks the primary AREDN (HTTP) path. Claude rounds focused on API behavior, not browser-policy surfaces. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.2)* |
   153	| WL-M2 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Injected `<video>` can leak into accessibility tree without `aria-hidden="true"` + `tabindex="-1"`; adds ghost media control to TalkBack/VoiceOver rotor during navigation. *File: 2026-04-20-nav-keep-awake-r6-codex-cross-validation.md (F6.3)* |
   154	| WL-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Safety framing is load-bearing but imprecise: the causal chain "screen dims → nav stops → driver endangered" is wrong; the real risk is driver distraction from checking a dark phone. Sharpening the framing disciplines the scope: explains why G4 (no UI chrome) and NG3 (no alarms on backgrounding) are correct choices. *File: 2026-04-20-nav-keep-awake-r5-product.md (F5.1)* |
   155	
   156	**Cycle 4 subtotals:**
   157	- CODEX-EXCLUSIVE: 2 CRITICAL + 3 MAJOR → $46,080
   158	- CLAUDE-EXCLUSIVE: 1 MAJOR → $5,760
   159	
   160	---
   161	
   162	### Cycle 5: Nav voice TTM follow-up (2026-04-24)
   163	
   164	**Reviewers:** R1 (Claude/pinyon-sub-r1), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Codex)
   165	
   166	| ID | Severity | Exclusivity | Avoided cost | Description |
   167	|----|----------|-------------|-------------|-------------|
   168	| FU-C1 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | BFCache diagnosis overstated; proposed `pageshow persisted=true` listener does not cover tab-discard, renderer-recreation, or standalone-PWA process recreation return paths; fix can ship while the user-visible bug remains reproducible on non-BFCache return paths. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.2)* |
   169	| FU-C2 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | GPS-dropout recovery unspecified: after stale GPS + dead reckoning, the first recovered tick can fire a sharply-different prefix from what the driver expected (e.g., "now turn" vs "in quarter mile") with no stale/recovery guard. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.4)* |
   170	| FU-M1 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Net Issue-1 buffer gain at 25 mph is only +0.6 s after Issue-2 prefix cost, not +1.3 s as claimed in §4.2; 0.6 s is inside the driver-reaction envelope (0.8–1.5 s); spec G1 "≥2.8 s post-speech buffer" is not met. Known-wrong number left in spec body with correction buried in §9. *File: 2026-04-24-nav-voice-followup-r1-api-correctness.md (F1.3)* |
   171	| FU-M2 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Band-boundary test vector (290m → "In 1000 feet") is numerically ambiguous: implementer's natural "round then band-check" yields "In 1/4 mile," not "In 1000 feet"; test will fail; spec body and implementation are inconsistent on which check runs first. *File: 2026-04-24-nav-voice-followup-r1-api-correctness.md (F1.10)* |
   172	| FU-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Repeating same maneuver with two different live distances creates ambiguity: drivers interpret second prompt as correction, not escalation; no spec rule distinguishes far-tier-already-fired from fresh far-tier. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.3)* |
   173	| FU-M4 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | Restoring tab via synthetic `.click()` can blur active form input (e.g., route-start field) on BFCache return; route-regeneration behavior may trigger unexpectedly. *File: 2026-04-24-nav-voice-followup-r5-codex.md (F5.7)* |
   174	
   175	**Cycle 5 subtotals:**
   176	- CODEX-EXCLUSIVE: 2 CRITICAL → $86,400
   177	- CLAUDE-EXCLUSIVE: 4 MAJOR → $23,040
   178	
   179	---
   180	
   181	### Cycle 6: Nav voice picker (2026-04-21)
   182	
   183	**Reviewers:** R1 (Claude), R2 (Claude), R3 (Claude), R4 (Claude), R5 (Codex)
   184	
   185	| ID | Severity | Exclusivity | Avoided cost | Description |
   186	|----|----------|-------------|-------------|-------------|
   187	| VP-C1 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | Cloud-backed voices (`localService === false`) are included in the spec's voice list without warning; on an isolated AREDN mesh these voices silently stop speaking; preference feature becomes a field failure mode. Claude rounds focused on API correctness, not network-topology constraints. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.1)* |
   188	| VP-C2 | CRITICAL | CODEX-EXCLUSIVE | $43,200 | Custom `button role="radio"` widget lacks required keyboard interaction model: single tabbable item, arrow-key navigation, Space activation, roving tabindex. ARIA attributes are present but behavioral parity is absent; screen-reader and keyboard users get non-conforming behavior. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.2)* |
   189	| VP-M1 | MAJOR | CODEX-EXCLUSIVE | $5,760 | Auto-preview speaks over assistive-tech output: for VoiceOver/TalkBack, changing voice selection triggers immediate `speechSynthesis.speak()` at the exact moment screen reader announces the focused control; two speech channels overlap. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.3)* |
   190	| VP-M2 | MAJOR | CODEX-EXCLUSIVE | $5,760 | `utterance.lang = 'en-US'` hard-coded even when user selects `en-GB`/`en-AU`/`en-IN` voice; inconsistent locale tag asked of engine vs chosen voice; preview text uses US-centric street naming for non-US English locales. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.4)* |
   191	| VP-M3 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | `activePreviewUtterance` cleanup relies on `onend` event; W3C spec is explicit that cancelled utterances fire `onerror` only (`"interrupted"` or `"canceled"`), never `onend`; cleanup leaks; next `visibilitychange` kills the nav audio in flight. *File: 2026-04-21-nav-voice-picker-r1-api-correctness.md (F1.1)* |
   192	| VP-M4 | MAJOR | CLAUDE-EXCLUSIVE | $5,760 | 5-second empty-voice fallback collapses three different states (no Speech API, voices not yet enumerated, gate on user gesture) into one permanent "not supported" message; operators on mesh interpret as platform limitation rather than recoverable delay. *File: 2026-04-21-nav-voice-picker-r5-codex-cross-validation.md (F5.6)* |
   193	
   194	**Cycle 6 subtotals:**
   195	- CODEX-EXCLUSIVE: 2 CRITICAL + 2 MAJOR → $97,920
   196	- CLAUDE-EXCLUSIVE: 1 MAJOR + 1 MAJOR → $11,520
   197	
   198	---
   199	
   200	### Cycles 7 & 8: April 16 pipeline reviews (2026-04-16)
   201	
   202	**Reviewers:** Claude only (5 parallel lenses; no Codex round in these cycles)  
   203	**Note:** No Codex round was run for the NOAA pipeline review cycles. These are Claude-only catches that represent the baseline value of running Claude reviews at all — not cross-model exclusivity catches.
   204	
   205	These cycles are excluded from the exclusive-catch ROI calculation because cross-model comparison requires both sides to be present. They are mentioned for completeness: 40+ findings across concurrency, data integrity, error handling, memory, and performance. None can be classified CODEX-EXCLUSIVE or CROSS-CONFIRMED without a Codex round to compare against.
   206	
   207	---
   208	
   209	## ROI summary
   210	
   211	### Per-exclusivity subtotals
   212	
   213	| Category | CRITICAL findings | MAJOR findings | Avoided cost |
   214	|----------|-------------------|----------------|-------------|
   215	| CODEX-EXCLUSIVE | 12 | 10 | $204,960 |
   216	| CLAUDE-EXCLUSIVE | 4 | 11 | $92,640 |
   217	| **Total exclusive** | **16** | **21** | **$297,600** |
   218	
   219	CROSS-CONFIRMED and CONSENSUS findings (those caught by both model families independently) are excluded from this table. By definition, single-model review would have caught those eventually — they are not the basis of the cross-model pitch.
   220	
   221	### Annual cost vs avoided cost
   222	
   223	| Item | Cost |
   224	|------|------|
   225	| Claude Max subscription | $2,400/yr |
   226	| ChatGPT Plus (Codex CLI) | $240/yr |
   227	| **Total harness cost** | **$2,640/yr** |
   228	| **Avoided cost (exclusive catches only)** | **$297,600** |
   229	| **ROI multiple** | **~113×** |
   230	
   231	The ROI is overdetermined: even if two-thirds of the exclusive findings are discounted as "would have been caught eventually by QA or user testing," the remaining one-third still represents $99,200 in avoided cost — a 38× return.
   232	
   233	---
   234	
   235	## Caveats and what this analysis does NOT claim
   236	
   237	1. **Not all CRITICAL findings were certain to ship.** Some CRITICALs are spec-phase catches on a design that would have been further reviewed before implementation. The 30× production-bug multiplier is used conservatively only for findings that would have survived plan-writing and implementation (e.g., the TTM `start()` gap, the Terrarium formula, the pricing constants — all were present in the code or in near-final specs ready for implementation).
   238	
   239	2. **"Exclusive" attribution is best-effort, not proof.** The classification relies on the written review outputs. It is possible that a Claude reviewer noticed a finding but chose not to surface it, or that a Codex reviewer was influenced by having access to earlier Claude output in the file system (Codex reads the repo). Conservative attribution is used throughout.
   240	
   241	3. **Avoided-cost calculation assumes the bugs would have shipped without the harness.** In practice, some would have been caught in integration testing, user testing, or beta feedback. The NIST multipliers represent what bugs cost on average when they reach production, which is the appropriate baseline for the cost-of-not-reviewing calculation.
   242	
   243	4. **This does not claim Claude is better than Codex or vice versa.** The data shows each model has architectural strengths that the other lacks. Codex finds: cross-repo consistency checks, API contract violations against real-world browser docs, network-topology constraints (AREDN offline reality). Claude finds: framing defensibility, mathematical buffer calculations, spec-to-codebase discrepancies in format and API surface.
   244	
   245	5. **The $120/hr rate is a single-point estimate.** At $80/hr (conservative junior engineer), ROI is ~75×. At $160/hr (senior/FAANG), ROI is ~226×. The pitch holds at any reasonable rate.
   246	
   247	6. **Hardware costs are excluded.** The Pi 5 development machine ($150–$200) is a one-time cost not included in the $2,640/yr subscription figure.
   248	
   249	---
   250	
   251	## Reproduction
   252	
   253	Every finding row in this document links to a specific file and heading in `dev/adversarial/`. To audit a claim:
   254	
   255	1. Open the referenced file.
   256	2. Find the heading matching the finding ID.
   257	3. Verify the "Exclusivity" classification by searching other files in the same cycle for the same finding description.
   258	4. Apply the cost rubric from the Methodology section.
   259	
   260	The classification "CODEX-EXCLUSIVE" can be verified by searching the four Claude-round files for any mention of the specific finding. None of the CODEX-EXCLUSIVE findings listed here appear in the Claude-round files for that cycle.

exec
/bin/bash -lc "nl -ba dev/notes/cross-model-review-value-draft-v1.md | sed -n '260,420p'" in /home/administrator/Code/geographica
 succeeded in 0ms:
   260	The classification "CODEX-EXCLUSIVE" can be verified by searching the four Claude-round files for any mention of the specific finding. None of the CODEX-EXCLUSIVE findings listed here appear in the Claude-round files for that cycle.
   261	
   262	Cycles are grouped by spec:
   263	- **Cost methodology:** `2026-04-25-cost-methodology-r*.md`
   264	- **Ruler:** `2026-04-24-ruler-r*.md`
   265	- **Nav TTM:** `2026-04-20-nav-voice-ttm-r*.md`
   266	- **Nav wake-lock:** `2026-04-20-nav-keep-awake-r*.md`
   267	- **Nav TTM follow-up:** `2026-04-24-nav-voice-followup-r*.md`
   268	- **Nav voice picker:** `2026-04-21-nav-voice-picker-r*.md`
   269	
   270	---
   271	
   272	## Appendix: Top findings for the pitch narrative
   273	
   274	### Top 3 CODEX-EXCLUSIVE findings (for Cameron's pitch)
   275	
   276	**1. Cost pricing constants wrong by 3×, compounding to 5.6× total inflation (CM-C2 + CM-C1a)**  
   277	Codex independently fetched Anthropic's pricing documentation and LiteLLM's model pricing database, then cross-validated against `ccusage` output for the actual token counts. It identified both the wrong pricing constants ($15/$75 vs $5/$25) and the output-token double-counting from streaming partial records — a combination that inflated the headline number by 5.6×. Claude rounds R1 and R2 caught the pricing error after examining the files, but R5 was the first reviewer to also surface the streaming-dedup issue and to provide per-tier quantification with cross-validation evidence.
   278	
   279	**2. Editing-state click leakage into reverse-geocode handler (RL-C3)**  
   280	Codex traced the actual `queryRenderedFeatures` call at app.js:1622–1635 and found ruler layers absent from the five-layer exclusion list. Because `isActive()` is intentionally false in `editing` state, the existing suppression mechanism does not fire for vertex-select taps. Result: every vertex selection also opens a reverse-geocode popup. Claude rounds R1–R4 identified the `isActive()` boundary correctly but none independently checked what happens when a ruler layer is the hit target during editing.
   281	
   282	**3. `start()` route-start guarantees structurally false (TTM-C2 + TTM-C3)**  
   283	Codex identified that the TTM spec makes guarantees about route-start voice behavior (G2, G4) that cannot be satisfied by the current engine because `checkVoice()` is never called in `start()`. It then identified the secondary implication: satisfying G2/G4 requires changing nav-ui.js initialization order, which contradicts the spec's NG3 claim of "no nav-ui changes." Two mutually exclusive guarantees were in the spec simultaneously; Claude rounds focused on the `tick()` path and did not synthesize across the full call graph.
   284	
   285	### Top 3 CLAUDE-EXCLUSIVE findings (for Cameron's pitch)
   286	
   287	**1. Cache-write exclusion unjustified by the methodology's own standard (CM-C3)**  
   288	The R3 framing reviewer (Claude) identified that the methodology's claimed standard ("actual generation work") includes cache writes by its own definition — Anthropic charges for them because they represent compute. Excluding them from the headline with no argument is the single most vulnerable point in the pitch, because a hostile senior engineer will raise it immediately. Codex R5 did not surface this framing vulnerability; it focused on pricing accuracy and transcript-format questions.
   289	
   290	**2. TTM `distanceToManeuver` returns signed values (TTM-C1)**  
   291	Claude R1 traced the actual `distanceToCoordIndex` function at navigation.js:209–214 and found it returns `target - current` — a signed subtraction. Negative TTM passes every threshold, causing far-tier to fire for maneuvers the driver has already executed. This is a math correctness bug that would ship as "voice fires at wrong time" — the exact symptom the TTM redesign was intended to fix. Codex R6 focused on the start-time initialization path and did not surface this negative-distance hazard.
   292	
   293	**3. `activePreviewUtterance` cleanup relies on event that never fires (VP-M3)**  
   294	Claude R1 cited the W3C Web Speech API spec explicitly: "If this event fires, the end event must not be fired for this utterance." A cancelled utterance fires `onerror` (`"interrupted"` or `"canceled"`), never `onend`. The spec's cleanup handler wires `onend` only. On any preview-to-preview cancel, `activePreviewUtterance` leaks permanently. The next `visibilitychange → hidden` kills the nav audio in flight. Codex R5 covered accessibility, i18n, and offline concerns; it did not trace the SpeechSynthesis cancel-event semantics.
   295	
   296	---
   297	
   298	*Document produced by agent gravel · 2026-04-25*

exec
/bin/bash -lc "sed -n '1,220p' dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
---
round: 5
angle: Codex cross-validation
reviewer: OpenAI Codex CLI (outside-Claude perspective)
date: 2026-04-21
---

# Round 5 — Codex cross-validation

Independent review from outside the Claude model family. Four Claude rounds (R1 API correctness, R2 concurrency, R3 testing, R4 subagent executability) ran in parallel; this round formed its own view first, then cross-checked for overlap. Six findings across offline/AREDN, accessibility, i18n, consistency, and one novel angle.

**Captured from Codex stdout output; writer recorded after transcription from the live stream.**

---

### F5.1 — Spec allows user to save a cloud-backed voice that silently fails on AREDN mesh

- **Severity:** MUST-FIX
- **Angle hit:** offline
- **Claim in spec:** §1: "No network dependency"; §7.1 step 3b/3c resolves from the current voice list without any `localService` filter; §6.1 exposes the full installed voice list in `#pref-voice-select`.
- **Issue:** On the browsers Geographica is most likely to encounter in the field, `speechSynthesis.getVoices()` can include cloud-backed voices with `voice.localService === false`. On an isolated AREDN mesh, those voices are not reliable even if they worked during setup on home Wi-Fi or LTE. The current spec therefore lets the user save a voice that will silently stop speaking once the device is truly offline. That directly contradicts the offline-first premise and turns a preference feature into a field failure mode.
- **Proposed fix:** Amend §7 and §8 so the default candidate set is `en-*` voices with `localService !== false`. In the specific-voice dropdown, either hide non-local voices entirely or place them in a clearly separated "Cloud voices (internet required)" opt-in section that is collapsed by default. Add an error-matrix row: if a persisted specific voice resolves to `localService === false`, the module must fall back to the stored gender hint or browser default and surface a non-blocking warning in Preferences. Do not rely on `navigator.onLine`; on mesh devices it is not a trustworthy proxy for internet reachability.
- **Claude-blind-spot note:** API-focused review tends to stop at "the property exists" and generic web guidance often assumes internet is intermittently available. The AREDN constraint makes this materially more severe: remote voices are not just slower, they are incompatible with the deployment model.

---

### F5.2 — ARIA treatment is incomplete; spec defines custom radio widget without required keyboard model

- **Severity:** MUST-FIX
- **Angle hit:** a11y
- **Claim in spec:** §6.1 gives `.pref-voice-buttons` `role="radiogroup"` and each button `role="radio"` with `aria-checked`; §10.3 item 11 expects VoiceOver / TalkBack to read the group correctly.
- **Issue:** This is only the surface ARIA. A custom `button role="radio"` control also needs the radio-group interaction model: a single tabbable item, arrow-key navigation between options, Space activation, and deterministic focus behavior when selection changes. None of that is specified. Without it, screen-reader and keyboard users will get three separately tabbable buttons that announce as radios but do not behave like radios. That is exactly the class of custom-widget bug native form controls avoid.
- **Proposed fix:** Replace the custom button radios with native `<input type="radio">` controls and `<label>`s, matching the existing Units/Coordinates pattern already used in the sidebar. If the visual design must stay button-like, style the labels as segmented controls and keep the real radios visually hidden but accessible. If the custom-button approach is kept, §6.1 must explicitly require roving `tabindex`, Left/Right and Up/Down arrow movement, Space selection, and focus staying on the active radio per the WAI-ARIA radio-group pattern.
- **Claude-blind-spot note:** Code/spec reviews often over-credit the presence of ARIA attributes. The missing part is behavioral parity, and that gap is easy to miss if the review is not coming from an accessibility-first angle.

---

### F5.3 — Auto-preview is hostile to screen-reader flow; speaks over assistive-tech output

- **Severity:** SHOULD-FIX
- **Angle hit:** a11y
- **Claim in spec:** §3 Q3 and §9 require auto-preview on selection; §10.3 item 11 treats accessibility as "reads as a radio group" plus correct `aria-expanded`/hidden behavior.
- **Issue:** For a VoiceOver or TalkBack user, changing the selected voice is itself an audio interaction. Immediate `speechSynthesis.speak()` on every selection means Geographica starts talking at the exact moment the screen reader is trying to announce the newly focused control, checked state, or disclosure change. The result is overlapping speech, cut-off announcements, or a user who cannot tell whether the sound came from the screen reader or the preview engine. The current a11y section checks semantics, but not the end-to-end auditory experience.
- **Proposed fix:** Change §9 so preview is explicit, not implicit, for accessible flows. Concrete text: "Selection changes update state only. A separate `Preview voice` button speaks the sample phrase. This avoids interrupting screen-reader announcements." If auto-preview must remain for sighted/touch users, require an accessibility-safe fallback: no auto-preview on focus movement, no auto-preview when selection changes via arrow-key navigation, and a live-region text confirmation that does not compete with spoken AT output.
- **Claude-blind-spot note:** Testing and concurrency reviews usually model audio as a single channel. Screen-reader UX introduces a second speech channel, and that conflict is easy to miss unless you specifically imagine VoiceOver/TalkBack operation.

---

### F5.4 — Spec says `en-*` only, but preview text and language handling are hard-coded to U.S. English

- **Severity:** SHOULD-FIX
- **Angle hit:** i18n
- **Claim in spec:** NG4 limits scope to `en-*`; §9.2 hard-codes preview text to "In 500 feet, turn right onto Main Street." / metric variant and `lang = 'en-US'`; §4.2 leaves nav utterances at `utterance.lang = 'en-US'` even when a user selects a specific `en-GB`, `en-AU`, or `en-IN` voice.
- **Issue:** "English-only" is not the same as "U.S. English only." The current spec filters in non-US English voices but then forces U.S. phrasing and language tagging anyway. That creates two problems. First, the sample phrase is culturally narrow: `Main Street` plus `turn right` plus `feet` as the default example reads as U.S.-centric even when the chosen voice is Canadian, Australian, British, or Indian English. Second, hard-coding `utterance.lang = 'en-US'` while assigning a non-US specific voice is internally inconsistent; it asks the engine to speak one locale while the chosen voice advertises another.
- **Proposed fix:** Revise §9.2 and §4.2 so `utterance.lang` follows the resolved voice when a specific voice is selected, and otherwise uses the best available English locale from the resolved voice or `en`. Replace the sample phrase with a locale-neutral line such as "Continue for 500 feet. Next turn in 500 feet." / metric equivalent, or explicitly state that the sample text is only a temporary placeholder and must not encode U.S.-specific street naming. At minimum, stop hard-coding `en-US` when the user chose `en-GB`/`en-AU`/`en-IN`.
- **Claude-blind-spot note:** Earlier rounds were aimed at API correctness and testing, which biases toward "does speech happen" rather than "does this English-only spec quietly collapse all English locales into U.S. defaults."

---

### F5.5 — UI-state story for a missing specific voice is internally inconsistent and can silently flip later

- **Severity:** MUST-FIX
- **Angle hit:** consistency
- **Claim in spec:** §7.1 step 3b says `mode: "specific"` with a missing `voiceURI` falls through to `storedGenderHint`; §8 row 2 says "On next Preferences expand, the Male / Female button reflects the fallback state"; §5.4 never rewrites storage on this fallback.
- **Issue:** The spec mixes two different concepts: persisted preference and effective resolution. If a saved specific voice disappears, the stored mode remains `specific`, but the UI is supposed to light a gender button as though the preference were now `gender`. That creates a misleading state. The user sees Female selected, but the underlying data still says "specific voice X." If that original voice reappears after `voiceschanged` or an OS change, behavior flips back to the specific voice without any user action, because storage was never normalized. The UI therefore does not truthfully represent the saved preference.
- **Proposed fix:** Pick one model and state it explicitly. Preferred option: keep the persisted mode as `specific`, keep the dropdown selection in an explicit unavailable state, and show helper text such as "Saved voice unavailable; currently falling back to Female." Do not light the gender buttons unless the module also normalizes storage to `mode: "gender"` on first fallback. If you want the UI to show Female as selected, then §7/§8 must also require rewriting localStorage from `specific` to `gender` at that point.
- **Claude-blind-spot note:** This is the kind of state-model inconsistency that gets missed when reviews focus on execution paths rather than what the UI is promising to the user over time.

---

### F5.6 — The 5-second "not supported" fallback collapses three different states

- **Severity:** SHOULD-FIX
- **Angle hit:** novel
- **Claim in spec:** §7.3 and §8 row 4 treat "`getVoices()` is still empty after 5 seconds" as equivalent to "voice selection is not supported on this browser."
- **Issue:** On Geographica's actual target devices, an empty voice list can mean at least three different things: browser truly lacks speech synthesis selection, voices have not enumerated yet, or the browser only exposes voices after a user-gesture speech prime. Those are materially different operational states, but the spec collapses them into one permanent-looking stub message. That is especially risky on offline mesh deployments because operators will interpret "not supported" as a product/platform limitation rather than a delayed-enumeration condition they can recover from.
- **Proposed fix:** Split the state machine and the user text. Add a transient "Detecting available voices..." state during bootstrap, and reserve "not supported" only for a stronger negative signal than "still empty after 5 seconds." If the list is empty but `speechSynthesis` exists, the UI should stay in a recoverable state with retry text such as "Voices not available yet on this device" plus a manual `Retry voice detection` action. The permanent unsupported stub should be the last resort, not the first timeout.
- **Claude-blind-spot note:** Browser-API and testability reviews often treat timeout-based degradation as acceptable. In an offline-first field tool, the wording of degradation matters because operators use it to decide whether the system or their environment is at fault.

---

## Non-findings appendix

- No material disagreement with the earlier Claude rounds on their core concerns after cross-checking them. The strongest overlap is the remote-voice/offline issue (independently reached via AREDN deployment constraint rather than generic Web Speech API analysis — see F5.1 vs F1.8).
- Not worth additional review energy on the spec's anti-Shrek regression test idea. Low signal, but also not the highest-risk defect class in this design.

## Summary

- **MUST-FIX (3):** F5.1 (offline/AREDN violation via cloud voices), F5.2 (a11y radio-group keyboard model missing), F5.5 (UI-state inconsistency on missing voice).
- **SHOULD-FIX (3):** F5.3 (auto-preview over screen readers), F5.4 (i18n / hard-coded en-US), F5.6 (timeout-state collapsing).

Outside-Claude value-add: F5.2 (a11y behavioral parity beyond ARIA), F5.3 (screen-reader audio-channel conflict), F5.4 (en-* ≠ en-US), F5.5 (state-model promise vs. persistence), F5.6 (degradation wording on mesh). F5.1 is high-severity overlap with F1.8 but with a sharper offline-first framing.

exec
/bin/bash -lc "grep -RInE \"F5\\.6|5-second empty-voice fallback|not supported|activePreviewUtterance|onend|onerror|interrupted|canceled\" dev/adversarial/2026-04-21-nav-voice-picker-r*.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:12:The single most severe problem is F1.1: the spec's `activePreviewUtterance` tracking relies on `onend`/`onerror` being called on a cancelled utterance, but per the W3C spec the *only* event a cancelled utterance gets is a dispatched `error` event with code `"interrupted"` (when speaking) or `"canceled"` (when still queued) — and it explicitly forbids `end`. The spec's handler wording ("onend/onerror") is fine in principle, but §9.2 only assigns text/lang/rate/voice — it never assigns `onend` or `onerror`, and the §9.3 prose doesn't make clear that BOTH handlers are required. A single-handler implementation (common mistake) would leak `activePreviewUtterance` forever the first time the user triggers a preview-to-preview cancel, which in turn means the `visibilitychange` handler would incorrectly cancel nav audio after the first preview.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:16:### F1.1 — `activePreviewUtterance` cleanup relies on an event that never fires
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:20:**Claim in spec:** §9.3: *"`activePreviewUtterance` is cleared in the utterance's `onend` / `onerror` handler as well."* And §9.2 lists only `text`, `lang`, `rate`, `voice` as the properties assigned on the preview utterance — `onend`/`onerror` are never mentioned as assigned.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:22:**Reality:** The W3C Web Speech API spec is explicit: when `cancel()` is called on a currently-speaking utterance, an `error` event fires with `error === "interrupted"`; when it's called on a queued-not-yet-spoken utterance, an `error` event fires with `error === "canceled"`. In both cases, **"If this event fires, the end event must not be fired for this utterance."** (W3C Web Speech API spec §6, event dispatch order rules.) Therefore:
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:24:1. A preview-to-preview cancel (§9.2 last bullet, §9.3 third bullet) fires *only* `onerror`, not `onend`.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:25:2. Listening on only `onend` means `activePreviewUtterance` leaks on every cancel-then-speak cycle.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:26:3. Real-browser corroboration: Chrome fires `error` with code `"interrupted"` on cancel; Safari fires `error` (type varies by version but never `end`); Firefox matches the spec. See MDN `SpeechSynthesisErrorEvent` + https://webaudio.github.io/web-speech-api/#events (enumerated list includes both `canceled` and `interrupted`).
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:28:**Impact:** If the implementer wires only `onend` (natural first read of the spec: "clear when done"), `activePreviewUtterance` stays non-null after every preview cancel. The next `visibilitychange → hidden` or sidebar-close while nav is running will then call `speechSynthesis.cancel()`, which **will kill the nav utterance in flight** — exactly the regression §9.3 claims to prevent. This turns the whole preview-safety guarantee into a lie.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:33:utterance.onend   = function () { if (activePreviewUtterance === utterance) activePreviewUtterance = null; };
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:34:utterance.onerror = function () { if (activePreviewUtterance === utterance) activePreviewUtterance = null; };
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:37:Add an identity check (`activePreviewUtterance === utterance`) to guard against a stale handler from a prior utterance firing late after a new one is already assigned. Additionally, §10.1 should add a `preview-cleanup.test.mjs` that simulates cancel-fires-onerror-not-onend and asserts `activePreviewUtterance === null` afterwards.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:40:- W3C Web Speech API spec, §Errors: https://webaudio.github.io/web-speech-api/#speechsynthesiserrorcode — enumerates `"canceled"` and `"interrupted"`; "If this event fires, the end event must not be fired for this utterance."
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:53:- On sidebar close: `speechSynthesis.cancel()` if `activePreviewUtterance !== null`.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:56:The guard is the `activePreviewUtterance !== null` check, NOT a "is nav active" check. That's correct in principle, but it relies on F1.1 being fixed (if `activePreviewUtterance` leaks, the guard never rejects). More critically: **the spec nowhere forbids the user from opening the sidebar during nav**. A beta tester may well tap the sidebar toggle mid-trip to change units from imperial to metric, close it, and have the close-handler call `speechSynthesis.cancel()` — which per F1.1 kills nav audio. The "verify in task 1" note kicks the load-bearing invariant downstream.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:62:1. `activePreviewUtterance !== null` (the preview-scoped guard), AND
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:99:  4. 5-second fallback triggers, UI shows "not supported" despite voices existing
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:101:**Impact:** On a subset of Chrome loads, the Preferences voice group will show the "not supported" stub even though the browser supports voices perfectly. This is exactly the class of bug that's impossible to reproduce on the developer's machine but shows up on beta testers'.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:124:**Claim in spec:** §7.3 + §8 row 4: "Empty voice list after 5s" → hide the voice group, show the "Voice selection is not supported on this browser" stub.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:132:**Impact:** On iOS Safari, a user who opens the Preferences section BEFORE starting nav (the designed flow, per §3 Q3 and §9 "Preferences section only opens pre-nav") will see `getVoices() === []`, no `voiceschanged` ever fires, and after 5 seconds the stub appears saying "not supported" — which is false; voices just haven't been enumerated yet. The designed pre-nav flow is the one that fails hardest.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:136:1. §7.3 step 4: instead of giving up after 5s with the "not supported" stub, **poll** `getVoices()` every 500ms for 5 seconds (10 polls). Only show the stub if still empty after all polls AND `voiceschanged` never fired.
dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md:216:**Impact:** A user picks "Google UK English Female" from the dropdown on their Android tablet while connected to Wi-Fi (at home, testing). Drives into the field on AREDN-only (no LTE, no Wi-Fi). Nav fires, `speak()` silently fails (`onerror` with `"network"` code) — driver gets no audio guidance. The feature actively regresses reliability for the offline use case.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:19:### F2.1 — `activePreviewUtterance` has a cancel-then-speak clear race (critical)
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:24:> "`activePreviewUtterance` is cleared in the utterance's `onend` / `onerror` handler as well."
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:28:1. t=0: User clicks Male. `cancel()` runs (no-op, nothing active). New utterance M is built. `activePreviewUtterance = M`. `speak(M)`. `M.onstart` fires. M speaking.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:29:2. t=200ms: User clicks Female. Code path: `cancel()` → `activePreviewUtterance = F` → `speak(F)`.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:30:3. `cancel()` is not actually synchronous in terms of the `onend` delivery — Chrome, WebKit, and Firefox all queue utterance-end events on the main task loop. `M.onend` (or `onerror`) fires **after** `activePreviewUtterance = F` has already been assigned.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:31:4. The `onend` handler the spec describes clears `activePreviewUtterance` unconditionally. `activePreviewUtterance` becomes `null` while F is still in flight.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:32:5. User closes sidebar at t=400ms. Handler checks `activePreviewUtterance !== null` → **false** → does NOT cancel F. F keeps speaking after sidebar close.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:36:**Proposed fix:** Mirror wake-lock.js's generation-counter pattern. Module-private `previewGeneration = 0`. Every new preview bumps it: `var myGen = ++previewGeneration; activePreviewUtterance = u; u.onend = u.onerror = function () { if (myGen === previewGeneration) activePreviewUtterance = null; };`. The `onend` only clears if this utterance is still the active one.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:38:**Test to add:** In `preview-gate.test.mjs`, mock `speechSynthesis` with queued async `onend` delivery (via `queueMicrotask` or `setTimeout(..., 0)`). Fire two `click` events back-to-back on Male then Female. Then fire the stale M.onend. Assert `activePreviewUtterance === F` (not null). Then simulate sidebar close; assert `speechSynthesis.cancel()` was called.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:42:### F2.2 — `speechSynthesis.cancel()` has no synchronous `onend` contract across browsers
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:50:1. On Safari iOS, `speechSynthesis.cancel()` is documented to flush the queue but `SpeechSynthesisUtterance.onend` may not fire at all for cancelled utterances (WebKit bug #146484, still open as of 2024). The spec's §9.3 clears `activePreviewUtterance` in `onend` / `onerror`.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:51:2. User clicks Male. M starts. User closes sidebar. Handler sees `activePreviewUtterance = M`, calls `cancel()`. M stops speaking. But `M.onend` never fires on iOS Safari.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:52:3. `activePreviewUtterance` stays pointing at M forever.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:53:4. User opens sidebar again, clicks Female. F is set as `activePreviewUtterance`. cancel-then-speak runs. `F.onend` (eventually) fires and clears `activePreviewUtterance`. OK for this case.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:54:5. But if user never clicks another voice button, `activePreviewUtterance` holds a stale `M` reference for the rest of the session. On subsequent `visibilitychange → hidden`, the handler sees non-null and fires `cancel()` — cancelling any *nav utterance* currently in flight. This violates §G4 / §9.3 "must never interrupt an active nav utterance".
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:56:**Impact:** On iOS Safari, a single preview → sidebar-close sequence permanently arms the `visibilitychange` handler to nuke active nav voice lines. User pauses nav, Apple Maps takes over the screen momentarily (CarPlay, notification), comes back — next nav prompt got interrupted because the stale preview-utterance reference triggered a `cancel()`.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:58:**Proposed fix:** (a) Clear `activePreviewUtterance = null` synchronously *at the point of calling cancel* — don't rely on `onend`. (b) Also clear it at the top of the next-utterance build, before calling `cancel()` for the new one. `onend` becomes a belt-and-suspenders clear that guards on generation counter per F2.1.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:60:**Test to add:** In `preview-gate.test.mjs`, mock `speechSynthesis.cancel()` to NOT fire `onend` (iOS Safari semantics). Start preview M. Close sidebar (calls cancel). Simulate visibilitychange-hidden. Assert `speechSynthesis.cancel()` was NOT called a second time. (Additionally: start a nav-style utterance after closing the sidebar and assert it isn't interrupted.)
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:114:> §9.3: "On sidebar close: if `activePreviewUtterance !== null` → `speechSynthesis.cancel()`."
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:123:**Scenario:** User clicks Male. Preview starts. User taps map area outside sidebar (overlay click). Sidebar closes via path (2). Voice-picker never hears about it. `previewArmed` stays true. `activePreviewUtterance` stays set. Preview keeps speaking while map is in full view. User then clicks Female 10s later (via hamburger reopen) — preview fires as expected, but the *previous* preview speaking through map interaction was a regression.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:229:> "On `visibilitychange` → hidden: if `activePreviewUtterance !== null` → `speechSynthesis.cancel()`."
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:232:1. User clicks Male. Preview starts. `activePreviewUtterance = M`.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:233:2. Phone receives a call. `visibilitychange → hidden`. Cancel fires. M stops. `activePreviewUtterance` clears (via `onend` or F2.1's generation-counter fix).
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:255:2. Each click: cancel → speak. 6 calls. Per WebKit and Chromium, rapid `cancel()` + `speak()` sequences can leave the engine in a "speaking-but-silent" state where `speechSynthesis.speaking === true` but no audio is emitted. No `onerror` fires. This is observed across multiple reports; no official fix as of 2024.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:262:**Proposed fix:** (a) Debounce preview by ~150ms — only speak after clicks settle. (b) Explicit cache invalidation on any write to `nav-voice-pref`. (c) Ensure `activePreviewUtterance`-vs-generation-counter logic (F2.1 fix) applies.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:275:**Race scenario:** Most of the races above (F2.1, F2.2, F2.3, F2.4, F2.10, F2.11) depend on `speechSynthesis.speak()` being async-effectful — `onend`/`onstart` fire after the current microtask. If the mock fires `onend` synchronously inside `speak()`, none of these race windows exist in tests. Tests pass. Production still races.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:279:**Proposed fix:** §10.1 must add a test infrastructure requirement: **the speechSynthesis mock MUST deliver `onstart` / `onend` / `onerror` asynchronously via `queueMicrotask` or `setTimeout(..., 0)`, matching browser semantics**. Include a meta-test that asserts the mock does this, to prevent future test rewrites from regressing to synchronous behavior.
dev/adversarial/2026-04-21-nav-voice-picker-r2-concurrency.md:291:**Most subtle race:** F2.1 — the `onend` / clear-on-cancel race across rapid button clicks. The spec's `activePreviewUtterance` pattern appears correct but inverts itself under async `onend` delivery: the stale utterance's `onend` clears the *new* utterance's tracking state, disabling the very cancel path the feature relies on.
dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:71:### F5.6 — The 5-second "not supported" fallback collapses three different states
dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:75:- **Claim in spec:** §7.3 and §8 row 4 treat "`getVoices()` is still empty after 5 seconds" as equivalent to "voice selection is not supported on this browser."
dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:76:- **Issue:** On Geographica's actual target devices, an empty voice list can mean at least three different things: browser truly lacks speech synthesis selection, voices have not enumerated yet, or the browser only exposes voices after a user-gesture speech prime. Those are materially different operational states, but the spec collapses them into one permanent-looking stub message. That is especially risky on offline mesh deployments because operators will interpret "not supported" as a product/platform limitation rather than a delayed-enumeration condition they can recover from.
dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:77:- **Proposed fix:** Split the state machine and the user text. Add a transient "Detecting available voices..." state during bootstrap, and reserve "not supported" only for a stronger negative signal than "still empty after 5 seconds." If the list is empty but `speechSynthesis` exists, the UI should stay in a recoverable state with retry text such as "Voices not available yet on this device" plus a manual `Retry voice detection` action. The permanent unsupported stub should be the last resort, not the first timeout.
dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:90:- **SHOULD-FIX (3):** F5.3 (auto-preview over screen readers), F5.4 (i18n / hard-coded en-US), F5.6 (timeout-state collapsing).
dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:92:Outside-Claude value-add: F5.2 (a11y behavioral parity beyond ARIA), F5.3 (screen-reader audio-channel conflict), F5.4 (en-* ≠ en-US), F5.5 (state-model promise vs. persistence), F5.6 (degradation wording on mesh). F5.1 is high-severity overlap with F1.8 but with a sharper offline-first framing.

exec
/bin/bash -lc "sed -n '1,220p' dev/adversarial/2026-04-21-nav-voice-picker-r1-api-correctness.md" in /home/administrator/Code/geographica
 succeeded in 0ms:
---
round: 1
angle: Web Speech API correctness
reviewer: general-purpose (Claude Opus 4.7)
date: 2026-04-21
---

# Round 1 — Web Speech API correctness

Nine findings against `docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md`. Focus: places where the spec's behavioral assumptions diverge from what the W3C Web Speech API spec and real browsers actually do. Three MUST-FIX (F1.1, F1.2, F1.4), four SHOULD-FIX, two NICE-TO-HAVE.

The single most severe problem is F1.1: the spec's `activePreviewUtterance` tracking relies on `onend`/`onerror` being called on a cancelled utterance, but per the W3C spec the *only* event a cancelled utterance gets is a dispatched `error` event with code `"interrupted"` (when speaking) or `"canceled"` (when still queued) — and it explicitly forbids `end`. The spec's handler wording ("onend/onerror") is fine in principle, but §9.2 only assigns text/lang/rate/voice — it never assigns `onend` or `onerror`, and the §9.3 prose doesn't make clear that BOTH handlers are required. A single-handler implementation (common mistake) would leak `activePreviewUtterance` forever the first time the user triggers a preview-to-preview cancel, which in turn means the `visibilitychange` handler would incorrectly cancel nav audio after the first preview.

---

### F1.1 — `activePreviewUtterance` cleanup relies on an event that never fires

**Severity:** MUST-FIX

**Claim in spec:** §9.3: *"`activePreviewUtterance` is cleared in the utterance's `onend` / `onerror` handler as well."* And §9.2 lists only `text`, `lang`, `rate`, `voice` as the properties assigned on the preview utterance — `onend`/`onerror` are never mentioned as assigned.

**Reality:** The W3C Web Speech API spec is explicit: when `cancel()` is called on a currently-speaking utterance, an `error` event fires with `error === "interrupted"`; when it's called on a queued-not-yet-spoken utterance, an `error` event fires with `error === "canceled"`. In both cases, **"If this event fires, the end event must not be fired for this utterance."** (W3C Web Speech API spec §6, event dispatch order rules.) Therefore:

1. A preview-to-preview cancel (§9.2 last bullet, §9.3 third bullet) fires *only* `onerror`, not `onend`.
2. Listening on only `onend` means `activePreviewUtterance` leaks on every cancel-then-speak cycle.
3. Real-browser corroboration: Chrome fires `error` with code `"interrupted"` on cancel; Safari fires `error` (type varies by version but never `end`); Firefox matches the spec. See MDN `SpeechSynthesisErrorEvent` + https://webaudio.github.io/web-speech-api/#events (enumerated list includes both `canceled` and `interrupted`).

**Impact:** If the implementer wires only `onend` (natural first read of the spec: "clear when done"), `activePreviewUtterance` stays non-null after every preview cancel. The next `visibilitychange → hidden` or sidebar-close while nav is running will then call `speechSynthesis.cancel()`, which **will kill the nav utterance in flight** — exactly the regression §9.3 claims to prevent. This turns the whole preview-safety guarantee into a lie.

**Proposed fix:** §9.2: explicitly enumerate the three handlers that must be assigned:

```js
utterance.onend   = function () { if (activePreviewUtterance === utterance) activePreviewUtterance = null; };
utterance.onerror = function () { if (activePreviewUtterance === utterance) activePreviewUtterance = null; };
```

Add an identity check (`activePreviewUtterance === utterance`) to guard against a stale handler from a prior utterance firing late after a new one is already assigned. Additionally, §10.1 should add a `preview-cleanup.test.mjs` that simulates cancel-fires-onerror-not-onend and asserts `activePreviewUtterance === null` afterwards.

**Sources:**
- W3C Web Speech API spec, §Errors: https://webaudio.github.io/web-speech-api/#speechsynthesiserrorcode — enumerates `"canceled"` and `"interrupted"`; "If this event fires, the end event must not be fired for this utterance."
- MDN SpeechSynthesisErrorEvent: https://developer.mozilla.org/en-US/docs/Web/API/SpeechSynthesisErrorEvent

---

### F1.2 — Sidebar-close can still cancel nav audio in the PWA/background-open path

**Severity:** MUST-FIX

**Claim in spec:** §9.3: *"This is safe — no nav utterance can be in flight during the Preferences interaction cycle because the Preferences section only opens pre-nav (collapsed/hidden during active nav by existing sidebar behavior, verify in task 1 of the plan)."*

**Reality:** The spec hedges this with "verify in task 1 of the plan" but then already codes the assumption into §9.3's first two bullets:

- On sidebar close: `speechSynthesis.cancel()` if `activePreviewUtterance !== null`.
- On `visibilitychange → hidden`: same.

The guard is the `activePreviewUtterance !== null` check, NOT a "is nav active" check. That's correct in principle, but it relies on F1.1 being fixed (if `activePreviewUtterance` leaks, the guard never rejects). More critically: **the spec nowhere forbids the user from opening the sidebar during nav**. A beta tester may well tap the sidebar toggle mid-trip to change units from imperial to metric, close it, and have the close-handler call `speechSynthesis.cancel()` — which per F1.1 kills nav audio. The "verify in task 1" note kicks the load-bearing invariant downstream.

**Impact:** The claim "no nav utterance can be in flight during Preferences interaction" is either (a) false today, or (b) an implicit coupling between sidebar-state and nav-state that must be enforced somewhere. If (a), the feature silences the driver mid-turn. If (b), the plan needs an explicit task to enforce the coupling before the voice-picker ships.

**Proposed fix:** Belt-and-suspenders. §9.3 should require BOTH guards:

1. `activePreviewUtterance !== null` (the preview-scoped guard), AND
2. `!document.body.classList.contains('nav-active')` or an equivalent explicit "is nav running" check (use the existing `speechAvailable && !muted` plus a nav-engine-state read from `nav.isActive()` or similar).

Even if the sidebar-is-collapsed-during-nav invariant holds today, the double-guard is cheap and removes a load-bearing assumption from a frontend-only refactor.

**Sources:** Code inspection of `frontend/nav-ui.js:494-501` — the existing `onVoice` has no coupling to sidebar state. Any caller-side assumption about sidebar availability is exactly the kind of invariant that breaks 6 months later when someone else edits the sidebar module.

---

### F1.3 — `getVoices()` array reference is NOT guaranteed stable across calls on Chrome

**Severity:** SHOULD-FIX

**Claim in spec:** §7.2: *"`getVoices()` returns the same array reference between `voiceschanged` events in all supported browsers. We cache the last-returned `SpeechSynthesisVoice` keyed by `(mode, gender, voiceURI)`. On `voiceschanged` fire, cache is cleared."*

**Reality:** The W3C spec does not guarantee reference stability. MDN says: "Returns a list... of all the available voices on the current device" — "returns a list" is a new list, not a stable ref. Chromium's implementation creates a fresh V8 array on every call (wrapping the same underlying voice objects). Firefox's implementation similarly returns a fresh array. The *voice objects themselves* are generally identity-stable between `voiceschanged` events, but the enclosing array is not.

**Impact:** The spec's memoization strategy is sound — it doesn't actually need reference stability, since the key is `(mode, gender, voiceURI)` (not the array ref). But §7.2 asserts something false, and a future reader or implementer might rely on it (e.g., using `lastArr === getVoices()` as a cheap "has changed" test instead of subscribing to `voiceschanged`). Writing false claims about browser behavior into a spec is an adversarial-review foot-gun.

**Proposed fix:** §7.2 — replace first sentence with: *"The module caches the resolved `SpeechSynthesisVoice` keyed by `(mode, gender, voiceURI)`. Cache is invalidated on every `voiceschanged` event. We do not rely on `getVoices()` returning the same array reference across calls — only on the individual voice object identities being stable between `voiceschanged` fires, which is sufficient for `utterance.voice = cached` to still match a present voice."*

**Sources:** W3C Web Speech API spec §5.2 `getVoices` (no reference-stability guarantee). Chromium source: `content/renderer/web_speech_synthesis_client_impl.cc` constructs a fresh `WebVector` on every `getVoices()` call.

---

### F1.4 — `voiceschanged` fires multiple times and may fire BEFORE `init()` runs

**Severity:** MUST-FIX

**Claim in spec:** §7.3: *"If it returns `[]`: register a `voiceschanged` handler that re-reads `getVoices()` and fires the module's own voice-list-refreshed callback. Also start a 5-second `setTimeout` fallback..."* The spec does not contemplate (a) `voiceschanged` firing multiple times in a single page lifetime, nor (b) the race where `getVoices()` populates between the `getVoices() === []` check and the `addEventListener('voiceschanged', ...)` call.

**Reality:**
- **Multiple firings:** Chrome documented to fire `voiceschanged` more than once during a single page load in multi-profile or user-with-network-voices setups (the first fire is local voices only; the second is after Google Cloud TTS voices finish enumerating). Known since ~2016 in the Chromium tracker; still present.
- **Race on init:** On Chrome, the common pattern (which the spec is about to adopt) has a known race: call `getVoices()` — empty — attach listener — but the synchronous-ish voice population can race with event registration, meaning the first `voiceschanged` may have already fired. MDN's canonical example mitigates with the "call `populateVoiceList()` immediately AND on `voiceschanged`" idiom — the spec's §7.3 step 1 does call `getVoices()` first, but if it's empty it does NOT re-poll after attaching the listener. A narrow race exists where:
  1. `init()` calls `getVoices()` → `[]`
  2. Browser dispatches `voiceschanged` between step 1 and step 3
  3. `init()` calls `addEventListener('voiceschanged', ...)` — too late, event missed
  4. 5-second fallback triggers, UI shows "not supported" despite voices existing

**Impact:** On a subset of Chrome loads, the Preferences voice group will show the "not supported" stub even though the browser supports voices perfectly. This is exactly the class of bug that's impossible to reproduce on the developer's machine but shows up on beta testers'.

**Proposed fix:** §7.3 update to the triple-check pattern used by every production implementation:

1. `var voices = getVoices();`
2. If non-empty, populate and mark ready.
3. Unconditionally `addEventListener('voiceschanged', onVoicesChanged)`, where `onVoicesChanged` is idempotent (re-reads voices, only emits a "list refreshed" callback if the fingerprint changed).
4. Re-poll `getVoices()` once more AFTER the listener is attached; if non-empty, synthesize a manual `voiceschanged`-equivalent call. This closes the race window.
5. 5-second fallback only fires if voices are still empty.

Additionally, §7.3 should explicitly state `voiceschanged` may fire multiple times and the handler must be idempotent. §10.1 `voiceschanged-bootstrap.test.mjs` should add: "`voiceschanged` fires twice in sequence → handler deduplicates → `onVoiceListChanged` callback not invoked redundantly if voice list unchanged."

**Sources:**
- MDN `SpeechSynthesis/voiceschanged_event`: "fires when the list of `SpeechSynthesisVoice` objects changes" — implies multiple firings.
- Chromium bug tracker — longstanding reports of multi-fire on systems with mixed local + cloud voices.
- MDN canonical pattern calls `populateVoiceList()` synchronously AND on event, which is the pattern the spec should match.

---

### F1.5 — Safari iOS may not fire `voiceschanged` reliably; the 5-second fallback should populate, not hide

**Severity:** SHOULD-FIX

**Claim in spec:** §7.3 + §8 row 4: "Empty voice list after 5s" → hide the voice group, show the "Voice selection is not supported on this browser" stub.

**Reality:** iOS Safari historically has two quirks:
1. `voiceschanged` event is **not consistently dispatched** on iOS Safari (especially iOS 14/15/16); voices are populated lazily and `getVoices()` may return voices on the Nth call without any event firing.
2. `getVoices()` on iOS Safari often requires a user gesture OR a prior `speechSynthesis.speak()` call (a "priming" utterance) to enumerate the full voice list. The first call returns `[]` or a very small subset even when voices exist; subsequent calls after a priming `speak()` return the full list.

The existing `primeSpeech()` at `nav-ui.js:649-654` is exactly this pattern, but it runs on user interaction (start-nav button), not on page load when VoicePicker's `init()` runs.

**Impact:** On iOS Safari, a user who opens the Preferences section BEFORE starting nav (the designed flow, per §3 Q3 and §9 "Preferences section only opens pre-nav") will see `getVoices() === []`, no `voiceschanged` ever fires, and after 5 seconds the stub appears saying "not supported" — which is false; voices just haven't been enumerated yet. The designed pre-nav flow is the one that fails hardest.

**Proposed fix:** Three changes:

1. §7.3 step 4: instead of giving up after 5s with the "not supported" stub, **poll** `getVoices()` every 500ms for 5 seconds (10 polls). Only show the stub if still empty after all polls AND `voiceschanged` never fired.
2. §7.3 add step 5: on iOS Safari (user-agent sniff for `/iPad|iPhone|iPod/`), do not attach the stub-on-empty fallback at all. Instead, when the user clicks a gender button and `getVoices() === []`, fire a silent priming utterance (`new SpeechSynthesisUtterance(' '); u.volume = 0; speechSynthesis.speak(u)`) and poll again. This mirrors `primeSpeech()` but for the Preferences flow.
3. §8 row 4: add a note that iOS Safari's empty list is "pending enumeration, not unsupported" and the handling differs.

**Sources:**
- Apple Developer Forums: long-standing thread about iOS Safari speech synthesis voice enumeration requiring user-gesture priming.
- WebKit bug tracker bugs on `SpeechSynthesis::voicesDidChange` firing logic for iOS.
- The existing `primeSpeech()` function in this very codebase exists because of exactly this quirk.

---

### F1.6 — `voiceURI` is NOT stable and the fallback assumes more than it should

**Severity:** SHOULD-FIX

**Claim in spec:** §5.1 stores `voiceURI: "com.apple.ttsbundle.Samantha-compact"` as the specific-voice identifier. §8 Scenario 2 notes only the "saved voice uninstalled" case.

**Reality:** MDN and the W3C spec explicitly decline to guarantee `voiceURI` stability: *"a generic URI and can point to local or remote services."* Known instability cases:
1. **macOS voice upgrades** — Apple changes the voice bundle identifier across OS versions (e.g., `com.apple.speech.synthesis.voice.samantha` → `com.apple.ttsbundle.siri_female_en-US_compact` on newer versions). A user on macOS 14 → 15 can see the same voice with a different `voiceURI`.
2. **Firefox macOS** — uses `urn:moz-tts:osx:com.apple.speech.synthesis.voice.daniel` (per MDN), prefixed; Chrome macOS uses `com.apple.speech.synthesis.voice.daniel` bare. A user who picks a voice in Chrome, then later loads Geographica in Firefox, will see their `voiceURI` not match anything.
3. **Chrome Android** — `voiceURI` is often the same as `name` (e.g., `"Google US English"`), which IS stable but NOT a URN.
4. **Edge Windows** — `voiceURI` like `"HKEY_LOCAL_MACHINE\\SOFTWARE\\Microsoft\\Speech\\Voices\\Tokens\\MSTTS_V110_enUS_DavidM"` — registry path, can change with Speech Platform upgrades.

**Impact:** §8 Scenario 2 handles the "uninstalled" case, but the "upgraded/renamed" case silently fails the same way. More importantly: the `storedGenderHint` fallback only covers voices present in `KNOWN_VOICES`. A user on older macOS picks "Samantha (Enhanced)" → `storedGenderHint = "female"` (matched). On macOS update, Samantha's `voiceURI` changes → fallback to gender → scans voices, first `en-*` voice that infers `"female"` wins → the user gets whatever voice was first, which could be "Whisper" (an unsettling low-volume voice on macOS). Not broken, but surprising.

**Proposed fix:**

1. §5.1: store a composite identifier — `{voiceURI, name, lang}` rather than `voiceURI` alone. On resolution, try `voiceURI` match first; if that fails, try `name + lang` match as a secondary lookup before falling through to `storedGenderHint`. This recovers the macOS-update case cleanly.
2. §7.1 step 3b: update the logic to "voiceURI match → name+lang match → storedGenderHint → null".
3. §8 Scenario 2: expand to "Saved voice not found by URI **or name**".

**Sources:**
- MDN SpeechSynthesisVoice/voiceURI: "generic URI", no stability claim.
- W3C Web Speech API spec §5.3: voiceURI is descriptive, not canonical.
- Firefox vs Chrome voiceURI format difference is documented and visible in MDN's own example.

---

### F1.7 — KNOWN_VOICES table has incorrect Apple names and is missing platform-specific suffixes

**Severity:** SHOULD-FIX

**Claim in spec:** §5.3 KNOWN_VOICES table lists bare names: `'Samantha': 'female', 'Alex': 'male', 'Daniel': 'male'`, etc. Substring fallback example for Google: `"Google US English Female"`.

**Reality:**
- **Apple voices:** On modern macOS/iOS (14+), `voice.name` typically returns the bare first name (`"Samantha"`) for the default/compact voices, but enhanced/premium variants report suffixes: `"Samantha (Enhanced)"`, `"Samantha (Premium)"`, `"Alex (Enhanced)"`. The spec's exact-token-after-splitting-on-common-separators inferGender logic will work IF the separator list includes parentheses and spaces. §5.3 says "splitting on common separators" but doesn't specify which. If it uses `/[\s\-]+/` it will fail on `"Samantha (Enhanced)"` because the token list becomes `["Samantha", "(Enhanced)"]` and `"(Enhanced)"` still matches `"Samantha"` as the first token — OK. But `"Samantha (Compact)"` → `["Samantha", "(Compact)"]` → also OK. So this actually works IF tokenization is sensible.
- **Google voices on Android Chrome:** `voice.name` returns `"Google US English"` (no gender in the name) for the default voice. The gender-embedded names like "Google US English Female" are **older Chrome desktop** (Google TTS extension era) — Android Chrome 90+ returns `"Google US English"` with no gender token. The spec's substring regex will return `null` for these, meaning ALL Google voices on Android will fall through to "No gender match" → device default.
- **Microsoft Edge on Windows:** `voice.name` is typically `"Microsoft David Desktop - English (United States)"` or just `"Microsoft David - English (United States)"` (the "Desktop" suffix is for SAPI5 legacy voices; newer Edge uses Win10 SAPI voices without "Desktop"). The spec's table lists just `'David': 'male'` — the "first token" rule after `"Microsoft David..."` split-on-space yields `"Microsoft"`, not `"David"`. The tokenization must explicitly skip `"Microsoft"` prefix tokens.

**Impact:** "Male" and "Female" buttons will resolve to the device default on Android Chrome (no gender inference for `"Google US English"`) and on Windows Edge (first token matches `"Microsoft"`, which isn't in the table). The whole point of the feature — gender selection — silently fails on two of the three target platforms from §10.3.

**Proposed fix:**

1. §5.3: rewrite `inferGender` algorithm explicitly:
   - Strip known prefix tokens: `["Microsoft", "Google", "Apple", "Siri"]`.
   - Strip known suffix tokens: `(Enhanced|Premium|Compact|Desktop|\(.*\))`.
   - Split remaining on `/[\s\-_]+/`.
   - For each remaining token, check `KNOWN_VOICES` (case-insensitive).
   - If no token matches, apply the substring `/female|woman|girl/i` and `/\bmale\b|\bman\b|\bboy\b/i` fallbacks.
2. §5.3: add Android-Chrome-specific voices to the table — `'Google US English': null` (no gender inference possible; requires user to pick specifically). Also accept hint from `voice.default`: on Android Chrome, `"Google US English"` is usually the only en-* voice and has `default: true`.
3. §10.1 `gender-inference.test.mjs`: explicitly test `"Microsoft David - English (United States)"` → `"male"`, `"Samantha (Enhanced)"` → `"female"`, `"Google US English"` → `null`, `"Google UK English Female"` (legacy) → `"female"`.

**Sources:**
- Code inspection: I don't have access to Android Chrome or Windows Edge on this Pi, but the voice-name format is well-documented in the `speechSynthesis.getVoices()` Stack-Overflow canonical answers and MDN voice-list examples.
- Windows SAPI5 voice naming convention: https://learn.microsoft.com/en-us/previous-versions/windows/desktop/ms717037(v=vs.85)

---

### F1.8 — `SpeechSynthesisVoice.localService` check missing; non-local voices require network

**Severity:** SHOULD-FIX

**Claim in spec:** Section 1 says: "The feature is entirely client-side... No network dependency." Section 5.3's substring regex matches "Google US English Female" — which on *desktop* Chrome is a network-dependent Google Cloud TTS voice (`localService: false`).

**Reality:** `SpeechSynthesisVoice` has a boolean `localService` property:
- `true` — voice runs on-device, no network.
- `false` — voice is provided by a remote service (Google Cloud TTS on desktop Chrome, etc.).

On an AREDN mesh network the Pi is offline by definition. The user's phone/tablet browser may have internet (cellular) or may not. If a user picks a remote voice (`localService: false`), `speechSynthesis.speak()` will hang or error when offline — and the error propagation depends on the browser. Geographica's whole raison d'être is offline-first.

**Impact:** A user picks "Google UK English Female" from the dropdown on their Android tablet while connected to Wi-Fi (at home, testing). Drives into the field on AREDN-only (no LTE, no Wi-Fi). Nav fires, `speak()` silently fails (`onerror` with `"network"` code) — driver gets no audio guidance. The feature actively regresses reliability for the offline use case.

**Proposed fix:**

1. §5.3 / §7.1: filter the voice list to `localService === true` by default. Offer a small checkbox "Include cloud voices (requires internet)" that unlocks the non-local voices but defaults off.

codex
I have enough to write the validation. The two headline issues are now clear: the citation/rubric story is shakier than the draft claims, and the pitch math is aimed at “buy both tools” even though the actual decision is “add Claude to an existing Codex shop.”
2026-04-25T20:39:03.665352Z ERROR codex_core::tools::router: error=patch rejected: writing outside of the project; rejected by user approval settings
codex
Unable to save to `dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md` because this workspace is read-only. Full validation follows.

# Codex methodology validation — cross-model review value analysis

**Reviewer model:** GPT-5.4 (Codex)  
**Date:** 2026-04-25  
**Scope:** independent methodology review of [dev/notes/cross-model-review-value-draft-v1.md](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md)  
**Author of analysis under review:** Claude Sonnet (agent moniker: gravel)

## Verdict

**ACCEPTABLE WITH MINOR REVISIONS**

The core thesis holds: cross-model review is clearly surfacing non-overlapping value. I would not send this exact draft to a hostile senior engineering audience yet because the citation chain is overstated, the attribution table has internal contradictions, and the ROI framing is aimed at “buy both tools” instead of the actual decision, which is “add Claude to an existing Codex shop.”

## Methodology assessment

- **Rubric basis:** Not clean enough as written. The draft cites “NIST SP 500-235 (2002)” at [cross-model-review-value-draft-v1.md](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:24), but NIST SP 500-235 is a 1996 structured-testing document, not the 2002 economic-impact report named in the sentence. The 2002 source is NIST Planning Report 02-3, *The Economic Impacts of Inadequate Infrastructure for Software Testing*. NIST supports “late-found bugs are expensive,” but it does not cleanly anchor this draft’s exact `1x / 5x / 30x` table. Sources checked: NIST SP 500-235 https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf and NIST Planning Report 02-3 summary https://samate.nist.gov/docs/econImpactSumm.v23.pdf
- **Cost multipliers:** `1x` for review-time catches is fine. `5x` for shipped MAJOR and `30x` for shipped CRITICAL are directionally plausible industry heuristics, but the draft overstates how directly NIST/IBM support those exact figures. Bigger issue: it applies software-defect escalation logic to memo/framing findings like CM-C3/C4/C5, which is a category error.
- **Engineer-hour estimates:** Mostly reasonable. `8h` for math/pricing, `12h` for behavioral correctness, `16h` for concurrency, `24h` for data integrity, `4h` for framing/doc cleanup all pass a smell test. The weak point is multiplier choice, not hour sizing.

## Attribution spot-checks (3-5 findings)

- **CM-C1a:** [draft line 80](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:80) labels the Opus pricing error `CODEX-EXCLUSIVE`, but [2026-04-25-cost-methodology-r1-math.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-25-cost-methodology-r1-math.md:15) and [2026-04-25-cost-methodology-r2-coverage.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:17) independently catch it too. The next row in the draft already admits this by calling the same root issue cross-confirmed. This should not be counted as exclusive ROI.
- **RL-C3:** [draft line 106](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:106) is mostly fair. Codex in [2026-04-24-ruler-r5-codex.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-24-ruler-r5-codex.md:15) traces the concrete `queryRenderedFeatures()` leak path. Claude material gets near it, especially [r3-ux-mobile-a11y.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:59), but Codex is the first sampled file to spell out the full mechanism. I would keep it, but mark it borderline rather than cleanly exclusive.
- **TTM-C1:** [draft line 132](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:132) is accurately `CLAUDE-EXCLUSIVE`. Claude R1 in [2026-04-20-nav-voice-ttm-r1-api-correctness.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:17) clearly catches the signed-distance hazard. Codex R6 in [2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:13) focuses elsewhere.
- **FU-M3 / FU-M4:** [draft lines 172-173](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:172) label both `CLAUDE-EXCLUSIVE`, but both cite [2026-04-24-nav-voice-followup-r5-codex.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:15). That is an internal contradiction. These are Codex findings by the cited evidence trail.
- **VP-M4:** [draft line 192](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:192) labels the 5-second voice fallback issue `CLAUDE-EXCLUSIVE`, but the cited source is [2026-04-21-nav-voice-picker-r5-codex-cross-validation.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:71). Again, internal contradiction.

## Production-multiplier defensibility

- **Cost-methodology pricing constants / double-counting:** These likely would have shipped into the public methodology without review. High multiplier justified, though I would present it as a strong heuristic rather than “NIST-backed 30x.”
- **TTM `distanceToManeuver` negative-return bug:** Plausibly shippable. It depends on adversarial geometry, jitter, and DR behavior that happy-path testing could miss. High multiplier is defensible, with some haircut for likely pre-release simulation or field-test discovery.
- **TTM `start()` gap / nav-ui coupling:** Real and important, but I do not buy full production-escape pricing. This is a visible route-start workflow that manual integration testing would likely catch before release.
- **Ruler editing-state reverse-geocode leak:** Valuable catch, but also the kind of issue a manual edit-flow smoke test would probably expose quickly. I would price it lower than a true escaped production incident.

## Independent ROI estimate

My independent estimate for the **whole two-model harness** is **about $190,000 avoided downstream cost**.

That is **within 50%** of `$297,600`, so I read this as directional cross-model agreement with more conservative calibration. The main reductions are:
- remove CM-C1a from exclusive ROI,
- fix obvious misattributions,
- reprice framing/memo-quality findings as rework rather than production defects,
- haircut several “would have shipped” assumptions for bugs likely to be caught in integration or field validation.

For the **actual purchase decision** in context, the relevant figure is not total harness ROI. The team already has Codex. The incremental question is Claude-only value.

My estimate for **incremental add-Claude value** is **about $52,000**, with a reasonable range of **$45,000-$60,000**.

## What the analysis does well

- It identifies a real cross-model complementarity pattern.
- It excludes cross-confirmed findings from the exclusive tally.
- It uses concrete file-backed findings instead of generic quality claims.
- It includes caveats rather than pretending certainty.

## Where it could be strengthened (if anything)

- Fix the NIST citation chain and stop implying those sources directly license the exact multiplier table.
- Separate software-defect economics from memo/framing-defect economics.
- Correct attribution contradictions for CM-C1a, FU-M3, FU-M4, and VP-M4.
- Reframe the pitch around the actual marginal decision: existing Codex baseline, Claude incremental spend, Claude-exclusive incremental value.

## Pitch-defensibility assessment

As a hostile senior engineer, I would **not** accept this exact draft yet.

I **would** accept a tightened v2. The underlying case is good. What blocks acceptance is not the thesis, but preventable sloppiness in attribution and source framing. Once those are fixed, the argument becomes defensible.
tokens used
147,045
Unable to save to `dev/adversarial/2026-04-25-cross-model-roi-validation-codex.md` because this workspace is read-only. Full validation follows.

# Codex methodology validation — cross-model review value analysis

**Reviewer model:** GPT-5.4 (Codex)  
**Date:** 2026-04-25  
**Scope:** independent methodology review of [dev/notes/cross-model-review-value-draft-v1.md](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md)  
**Author of analysis under review:** Claude Sonnet (agent moniker: gravel)

## Verdict

**ACCEPTABLE WITH MINOR REVISIONS**

The core thesis holds: cross-model review is clearly surfacing non-overlapping value. I would not send this exact draft to a hostile senior engineering audience yet because the citation chain is overstated, the attribution table has internal contradictions, and the ROI framing is aimed at “buy both tools” instead of the actual decision, which is “add Claude to an existing Codex shop.”

## Methodology assessment

- **Rubric basis:** Not clean enough as written. The draft cites “NIST SP 500-235 (2002)” at [cross-model-review-value-draft-v1.md](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:24), but NIST SP 500-235 is a 1996 structured-testing document, not the 2002 economic-impact report named in the sentence. The 2002 source is NIST Planning Report 02-3, *The Economic Impacts of Inadequate Infrastructure for Software Testing*. NIST supports “late-found bugs are expensive,” but it does not cleanly anchor this draft’s exact `1x / 5x / 30x` table. Sources checked: NIST SP 500-235 https://nvlpubs.nist.gov/nistpubs/Legacy/SP/nistspecialpublication500-235.pdf and NIST Planning Report 02-3 summary https://samate.nist.gov/docs/econImpactSumm.v23.pdf
- **Cost multipliers:** `1x` for review-time catches is fine. `5x` for shipped MAJOR and `30x` for shipped CRITICAL are directionally plausible industry heuristics, but the draft overstates how directly NIST/IBM support those exact figures. Bigger issue: it applies software-defect escalation logic to memo/framing findings like CM-C3/C4/C5, which is a category error.
- **Engineer-hour estimates:** Mostly reasonable. `8h` for math/pricing, `12h` for behavioral correctness, `16h` for concurrency, `24h` for data integrity, `4h` for framing/doc cleanup all pass a smell test. The weak point is multiplier choice, not hour sizing.

## Attribution spot-checks (3-5 findings)

- **CM-C1a:** [draft line 80](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:80) labels the Opus pricing error `CODEX-EXCLUSIVE`, but [2026-04-25-cost-methodology-r1-math.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-25-cost-methodology-r1-math.md:15) and [2026-04-25-cost-methodology-r2-coverage.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md:17) independently catch it too. The next row in the draft already admits this by calling the same root issue cross-confirmed. This should not be counted as exclusive ROI.
- **RL-C3:** [draft line 106](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:106) is mostly fair. Codex in [2026-04-24-ruler-r5-codex.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-24-ruler-r5-codex.md:15) traces the concrete `queryRenderedFeatures()` leak path. Claude material gets near it, especially [r3-ux-mobile-a11y.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-24-ruler-r3-ux-mobile-a11y.md:59), but Codex is the first sampled file to spell out the full mechanism. I would keep it, but mark it borderline rather than cleanly exclusive.
- **TTM-C1:** [draft line 132](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:132) is accurately `CLAUDE-EXCLUSIVE`. Claude R1 in [2026-04-20-nav-voice-ttm-r1-api-correctness.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-20-nav-voice-ttm-r1-api-correctness.md:17) clearly catches the signed-distance hazard. Codex R6 in [2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-20-nav-voice-ttm-r6-codex-cross-validation.md:13) focuses elsewhere.
- **FU-M3 / FU-M4:** [draft lines 172-173](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:172) label both `CLAUDE-EXCLUSIVE`, but both cite [2026-04-24-nav-voice-followup-r5-codex.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-24-nav-voice-followup-r5-codex.md:15). That is an internal contradiction. These are Codex findings by the cited evidence trail.
- **VP-M4:** [draft line 192](/home/administrator/Code/geographica/dev/notes/cross-model-review-value-draft-v1.md:192) labels the 5-second voice fallback issue `CLAUDE-EXCLUSIVE`, but the cited source is [2026-04-21-nav-voice-picker-r5-codex-cross-validation.md](/home/administrator/Code/geographica/dev/adversarial/2026-04-21-nav-voice-picker-r5-codex-cross-validation.md:71). Again, internal contradiction.

## Production-multiplier defensibility

- **Cost-methodology pricing constants / double-counting:** These likely would have shipped into the public methodology without review. High multiplier justified, though I would present it as a strong heuristic rather than “NIST-backed 30x.”
- **TTM `distanceToManeuver` negative-return bug:** Plausibly shippable. It depends on adversarial geometry, jitter, and DR behavior that happy-path testing could miss. High multiplier is defensible, with some haircut for likely pre-release simulation or field-test discovery.
- **TTM `start()` gap / nav-ui coupling:** Real and important, but I do not buy full production-escape pricing. This is a visible route-start workflow that manual integration testing would likely catch before release.
- **Ruler editing-state reverse-geocode leak:** Valuable catch, but also the kind of issue a manual edit-flow smoke test would probably expose quickly. I would price it lower than a true escaped production incident.

## Independent ROI estimate

My independent estimate for the **whole two-model harness** is **about $190,000 avoided downstream cost**.

That is **within 50%** of `$297,600`, so I read this as directional cross-model agreement with more conservative calibration. The main reductions are:
- remove CM-C1a from exclusive ROI,
- fix obvious misattributions,
- reprice framing/memo-quality findings as rework rather than production defects,
- haircut several “would have shipped” assumptions for bugs likely to be caught in integration or field validation.

For the **actual purchase decision** in context, the relevant figure is not total harness ROI. The team already has Codex. The incremental question is Claude-only value.

My estimate for **incremental add-Claude value** is **about $52,000**, with a reasonable range of **$45,000-$60,000**.

## What the analysis does well

- It identifies a real cross-model complementarity pattern.
- It excludes cross-confirmed findings from the exclusive tally.
- It uses concrete file-backed findings instead of generic quality claims.
- It includes caveats rather than pretending certainty.

## Where it could be strengthened (if anything)

- Fix the NIST citation chain and stop implying those sources directly license the exact multiplier table.
- Separate software-defect economics from memo/framing-defect economics.
- Correct attribution contradictions for CM-C1a, FU-M3, FU-M4, and VP-M4.
- Reframe the pitch around the actual marginal decision: existing Codex baseline, Claude incremental spend, Claude-exclusive incremental value.

## Pitch-defensibility assessment

As a hostile senior engineer, I would **not** accept this exact draft yet.

I **would** accept a tightened v2. The underlying case is good. What blocks acceptance is not the thesis, but preventable sloppiness in attribution and source framing. Once those are fixed, the argument becomes defensible.
