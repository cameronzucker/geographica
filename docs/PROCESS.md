# How Geographica was built

> A meta-story document. *What* Geographica does is in [`README.md`](../README.md) and [`SETUP.md`](SETUP.md). This page is *how it was built* — the workflow, the agent team, the adversarial-review discipline, and an honest read on what works and what does not.

---

## 1. What was built, in numbers

| Measure | Value |
|---|---:|
| Wall-clock window | 2026-04-06 → 2026-04-25 (19 days) |
| Commits on `dev` and `main` (combined) | 974 |
| Named agent monikers in commit trailers | 25 |
| Specs in [`docs/superpowers/specs/`](superpowers/specs/) | 42 |
| Plans in [`docs/superpowers/plans/`](superpowers/plans/) | 25 |
| Test files (`test_*.py`) | 105 |
| Persistent services + on-demand pipeline | 7 + 1 |
| Inference cost (uncached headline) | ~$284 |
| Inference cost (full Anthropic list price) | ~$3,593 |
| Cash outlay | ~$200 (one month of Claude Max) |

Numbers re-verified against the live repo on 2026-04-25. The two cost numbers are not in tension; both are honest and answer different questions. The headline (~$284) measures uncached input plus output at Anthropic's published per-model rates — the "what did the model actually generate" question. The full list price (~$3,593) adds cache-write and cache-read tokens at Anthropic's posted rates — the "what would Anthropic charge at full API list with no subscription" question. See [`COST_METHODOLOGY.md`](COST_METHODOLOGY.md) for the full reasoning behind each, the adversarial-review cycle that corrected the original audit (numbers were inflated 6-8× before the cycle ran), and the reference comparisons that anchor scale: ~$65–75K of equivalent senior-engineer labor for a 6-month build, ~$5–20K/yr off-the-shelf GIS license.

The 25-agent count reflects monikers picked by fresh sessions for grep-discoverability in the commit graph (`git log --grep="^Agent: "`); each session re-rolls a single-word lowercase identifier such as `juniper`, `manzanita`, `flint`, or `tumbleweed`. Sub-agents inherit the parent moniker plus an `-impl-` suffix, which is filtered out of this count. The convention exists for forensic recovery, not headcount inflation — see §4.

The 42-spec / 25-plan asymmetry is not a bug. Specs precede plans, and not every spec produces a plan: some get rejected at brainstorm review, some are split or merged into other plans, and some (cost methodology, ROI pitch, README overhaul) produce documentation rather than code. The ratio is a useful health signal — when it inverts (more plans than specs), it is usually a cue that planning is racing ahead of design.

---

## 2. The workflow

The build cycle has three phases. Every non-trivial feature passes through all three before any code lands.

1. **Brainstorm** — a structured Socratic exchange between the user and a single agent. Open questions are surfaced, design tradeoffs are made explicit, locked decisions are written down. Output: a draft spec.
2. **Adversarial spec review** — the draft is dispatched to multiple parallel reviewers (see §3) operating on different attack angles. CRITICAL findings block; MAJOR findings are triaged. Output: a revised spec (`v2`, sometimes `v3`) with the corrections folded in and the rejected findings documented as user decisions.
3. **TDD execution by parallel sub-agents** — the spec is decomposed into a numbered task plan, then dispatched task-by-task to implementer sub-agents. Each task is test-first, has its own code-review checkpoint, and ends with a commit. The orchestrator never writes implementation code itself.

The artifacts of all three phases are kept on disk: specs in `docs/superpowers/specs/`, plans in `docs/superpowers/plans/`, adversarial reviews in `dev/adversarial/`. Every claim in this document points at one or more of those files.

### Worked example — the navigation voice picker

A small but representative feature: let drivers choose a TTS voice for turn-by-turn audio prompts, persisted per device. Selected as the worked example because the receipts are complete, the cycle compressed into two days, and the feature exercised every part of the workflow.

| Phase | Date | Artifact | Notes |
|---|---|---|---|
| Brainstorm | 2026-04-20 | `c4be361` (initial spec) | Grew from a beta-tester request ("Shrek voice"). Brainstorm narrowed to the legitimate half — Default / Male / Female / specific installed voice — and explicitly hard-skipped voice cloning as out of scope. |
| Adversarial review | 2026-04-20 | `dev/adversarial/2026-04-21-nav-voice-picker-r{1..5}*.md` (commit `fbcfd7e`) | Five rounds — four parallel Sonnet sub-agents at distinct lenses (API correctness, concurrency, testing sufficiency, sub-agent executability) plus one Codex round for outside-Claude cross-validation. Surfaced 17 MUST-FIX, 25 SHOULD-FIX, 5 NICE-TO-HAVE findings. |
| Spec v2 | 2026-04-20 | `e6c8098` | Post-adversarial rewrite. Major structural changes: preview lifecycle reworked around a `previewGeneration` counter (closed three concurrency findings); explicit `nav-active` guard; `voiceschanged` triple-check + poll + iOS-priming bootstrap; `localService` filter for offline-first AREDN-mesh use; composite voice identifier `{voiceURI, name, lang}` so macOS upgrades don't silently lose the user's pick. |
| Plan | 2026-04-20 | `dceca6e` | 23 tasks across 7 phases, each with explicit test-first criteria and review checkpoints. |
| TDD execution | 2026-04-20 → 2026-04-21 | ~25 commits (e.g., `1afa330`, `8505590`, `528f783`, `5c09b5b`, `cb43e08`) | Each commit pairs an implementation task with its unit tests; reviews land between tasks. Field-verified on a live drive on 2026-04-21 (`af81fb5`). |

Total elapsed time: roughly two days from brainstorm to field-verified ship, including a sidebar tab-persistence regression caught and fixed during field testing (`f1687df`). Roughly one day was the brainstorm → spec v2 → plan; the second day was execution + verification.

The voice picker is not unusual. The same shape — brainstorm, multi-model adversarial review, plan, TDD execution by sub-agents — is the load-bearing pattern for nav wake-lock, the ruler tool, public lands, the imagery pipeline, the cost-methodology audit, and most other shipped features. The receipts for each are linked from `dev/implementation-log.md` and `CHANGELOG.md`.

---

## 3. Adversarial review patterns

Multi-model parallel review catches what single-model review misses. Each model family has different blind spots; cross-coverage matters more than depth on any single round.

The pattern: dispatch 3-4 review sub-agents in parallel, each given a distinct attack angle (math correctness, framing defensibility, coverage completeness, adversarial security, etc.). Add at least one round from a different model family — Codex (OpenAI GPT-5.4 via the local CLI) is the canonical out-of-Anthropic round in this project. Reviews land as committed markdown files in `dev/adversarial/`, named by date and topic, so the receipts survive context window resets.

### Worked example — the cost-methodology cycle (2026-04-25)

The audit script that produces this project's headline cost number (`scripts/audit_inference_cost.py`) is itself a product of this pattern. Before the cycle, the script and spec carried numbers around $2,500 uncached and $22,000 full-list-price. After the cycle, the corrected numbers are $284 uncached and $3,593 full — a 6-8× overstatement was caught and removed before any number reached public documentation.

Four reviewers ran in parallel, ~30 minutes wall-clock total:

| Round | Reviewer / model | Lens | Key finding |
|---|---|---|---|
| R1 | wren / Sonnet | Math correctness | Opus 4.6/4.7 priced at $15/M input + $75/M output (legacy 4.0/4.1 rates) instead of $5/M + $25/M — 3× overstatement on every Opus charge. ([`r1-math.md`](../dev/adversarial/2026-04-25-cost-methodology-r1-math.md)) |
| R2 | basalt / Sonnet | Coverage completeness | Same Opus pricing finding (cross-confirmed C1). Plus: Codex sessions for adversarial reviews were undisclosed; the methodology narrative had a gap. ([`r2-coverage.md`](../dev/adversarial/2026-04-25-cost-methodology-r2-coverage.md)) |
| R3 | flint / Sonnet | Framing defensibility | Three CRITICAL framing weaknesses a hostile reader would surface: cache-write exclusion was unjustified; "matches ccusage" was an appeal-to-tool, not a validation; the cache-reads-as-harness-artifact claim was asserted without argument. ([`r3-framing.md`](../dev/adversarial/2026-04-25-cost-methodology-r3-framing.md)) |
| R5 | Codex / GPT-5.4 | Independent cross-model | Output tokens were double-counted because Claude Code emits multiple JSONL streaming records per assistant turn, all carrying the same `message.id`. The script summed every record without dedup, inflating output counts ~1.85×. Independently flagged the wrong Opus pricing by fetching Anthropic's pricing page directly. ([`r5-codex.md`](../dev/adversarial/2026-04-25-cost-methodology-r5-codex.md)) |

The Codex round is the canonical "cross-model catch": three Sonnet rounds did not surface the streaming-dedup bug because the failure mode requires an outside-Anthropic mental model to think to look for it. R3 (Sonnet) flagged the framing of the cost number as suspicious *structurally*; R5 (Codex) caught the *mechanistic* root cause that produced the wrong number in the first place. Together, the two perspectives produced a complete fix in one cycle (`e456666` — both bugs corrected; `89f3da0` — methodology page revised against the corrected numbers).

Combined impact had the cycle not run: the README would have shipped with a ~$2,500 headline that any reader running the audit script with corrected pricing constants could disprove. The cost-methodology page would have failed the first hostile read.

### Quantified ROI

[`docs/CROSS_MODEL_REVIEW_VALUE.md`](CROSS_MODEL_REVIEW_VALUE.md) is a separate analysis that catalogs Claude-exclusive findings across six adversarial-review cycles in this project (cost methodology, ruler, nav TTM, wake-lock, TTM follow-up, voice picker). Conservative bottom-up tally: $22,500 of avoided rework against ~$10/yr of actual API consumption per developer for a typical adversarial-review cadence — roughly 450× ROI at the conservative bound, ~1,000× at Codex's independent estimate.

That document is also a worked example of the pattern it argues for. Codex caught structural and citation errors in the v1 draft (Mechanism B in the doc's terminology); the v2 it produced was internally consistent but built on a wrong cost-shape assumption (consumer subscription pricing rather than enterprise API consumption); the human author caught that on first read and forced the v3 reframe (Mechanism C — context-supply errors, the failure class cross-model review *does not* catch). All three phases are documented in the doc itself.

### What each reviewer is good at finding

Patterns observed across this project's six review cycles:

- **Sonnet rounds** — strong on detail-level correctness within a known frame (API contracts, concurrency races, state-machine completeness, test coverage). Tend to share Anthropic's mental model, so they miss errors that require reasoning from outside that frame.
- **Opus rounds** — used as the orchestrator for brainstorms and plan-writing; rarely used as a reviewer. Better at tradeoff reasoning than at line-level bug hunting.
- **Codex (GPT-5.4)** — the cross-model sanity check. Catches errors that depend on a different framing: pricing-source verification by direct WebFetch (cost methodology); offline-mesh field-failure modes Claude rounds didn't model (voice picker cloud-voice finding); tool-API semantics outside Anthropic's docs.
- **All families** — miss the same kinds of error: anything where the dispatch prompt itself supplies a wrong frame (Mechanism C). Human review is the only check for these.

---

## 4. Subagent orchestration

The orchestrator (a top-level Claude session) decomposes work into tasks and dispatches each to an implementer sub-agent. The orchestrator does not write code; the sub-agents do not see the full plan. This separation forces the orchestrator's plans to be self-contained per-task and the sub-agents' commits to be small and auditable.

Three discipline patterns hold the team together.

### Agent monikers

Every fresh session picks a single-word lowercase moniker (`juniper`, `manzanita`, `tumbleweed`) and includes it as an `Agent:` trailer on every commit alongside the `Co-Authored-By:` trailer. Sub-agents inherit the parent's moniker plus an `-impl-` suffix when relevant. The moniker is grep-friendly: `git log --grep="^Agent: juniper"` returns the full trail for a single session; `git log --all --grep="^Agent:"` enumerates every agent that has ever touched the repo.

The convention exists for forensics, not branding. When something goes sideways — a mysterious revert, an unexplained test regression, an unclear authorship question — the moniker trail provides triage data without requiring chronological reconstruction from timestamps. Two practical rules: monikers must avoid words already common in the codebase (so the grep is clean), and human first names are avoided (so the trail does not get confused with the user, beta testers, or co-authors). Plant, animal, and geographic nouns work well.

Monikers also flow into branch names (`agent-<moniker>/<topic>` for throwaway branches) and PR titles (`[juniper] <subject>`) when relevant, so the trail extends past commit messages into the broader repo history.

### Branch hygiene — no worktrees

Sub-agents work on `dev` (or shared feature branches) via `git checkout` in the main repo at `/home/administrator/Code/geographica`. The `git worktree` topology is banned project-wide.

The ban exists because of two near-misses in 2026-04 where sub-agents `cd`'d out of a worktree and performed destructive operations on the main repo's branch. One incident wiped seven commits from `dev`'s tip pointer (recovered via reflog). Worktree topology multiplies the blast radius of "sub-agent forgets which checkout it's in" errors, and the productivity benefit was not large enough to justify the recovery cost. Full write-up at [`docs/pitfalls/implementation-pitfalls.md`](pitfalls/implementation-pitfalls.md) §14.

### Destructive git commands are banned

Agents may not run `git reset --hard`, `git push --force`, `git checkout -- .`, `git clean -f`, `git branch -D`, history-rewriting rebase flags, `--no-verify`, `git reflog expire --expire=now`, or `git filter-branch`. There is no legitimate agent workflow that requires these; the impulse is always a recovery instinct ("start over from scratch") that should instead surface as a question to the human, not as a destructive operation.

The ban followed an incident on 2026-04-20 where a sub-agent ran `git reset --hard <other-branch>` on `dev` and wiped seven commits including a runtime-validated bug fix that had already shipped. Recovery took one merge with manual conflict resolution, but only because the commits were still reachable via reflog; two weeks later and `git gc` would have pruned them permanently. Non-destructive alternatives for every common scenario, and the recovery posture, are documented at [`docs/pitfalls/implementation-pitfalls.md`](pitfalls/implementation-pitfalls.md) §15.

---

## 5. What this enables (and what it doesn't)

The honest read.

### What works

- **Full-cycle features under good specs.** The pattern of brainstorm → adversarial review → TDD by sub-agents reliably produces working features when the spec captures the design tradeoffs explicitly. The voice picker, ruler, nav wake-lock, public lands layer, imagery pipeline, and cost-methodology audit script all shipped this way. Small features (1-3 days) and medium features (5-10 days) have similar success rates.
- **Repetitive grunt work.** Tasks with clear inputs, outputs, and verification criteria — schema migrations, test fixture generation, audit-log enumeration, port mapping audits — execute cleanly under sub-agent dispatch. Dispatching N parallel sub-agents on N independent files turns a day-long grind into a 30-minute parallel pass.
- **Bug hunts.** Three parallel hunters with different lenses (architectural, scale-performance, UX-mobile-a11y) reliably find more bugs than one hunter searching exhaustively. The `bug-hunt-cycle` skill formalizes this; it has been the source of most beta-readiness fix batches in this repo (see `dev/implementation-log.md` for cycle dates).
- **Documentation generation from artifacts.** This document, `COST_METHODOLOGY.md`, `CACHE_OPTIMIZATION.md`, and `CROSS_MODEL_REVIEW_VALUE.md` were all produced by sub-agents reading the on-disk receipts (`dev/adversarial/`, `dev/implementation-log.md`, commit history) and synthesizing. The discipline of keeping receipts on disk pays off most clearly here: documentation can be regenerated from primary sources rather than reconstructed from memory.

### What doesn't

- **Visual polish.** Aesthetic copy, brand voice, layout-and-balance decisions, and "this looks AI-generated" tells are weak spots. Sub-agents produce competent first drafts that often need a human pass to hit a professional bar. The `frontend-design` skill helps but does not close the gap.
- **Ambiguous specs.** A spec that punts on a tradeoff ("decide later", "TBD") becomes implementation drift. The cost of fixing drift after the fact is several times the cost of forcing the brainstorm to produce a locked decision. When the brainstorm cannot resolve the tradeoff, the right next step is to surface it to the human, not to dispatch.
- **Cross-task implicit state.** Sub-agents executing separate tasks do not share working memory. Anything that depends on "agent A noticed during task 3 that the X assumption was wrong, so agent B handling task 7 should adapt" must be captured explicitly in the plan or surfaced to the orchestrator as a blocking review checkpoint. Reliance on implicit shared context produces silent regressions.
- **Aesthetic copy.** Stilted prose from an over-aggressive style rule (such as the no-first-person rule applied to this document) is the cost of holding a discipline at scale. The discipline produces consistency; consistency reads as polish in aggregate even when individual sentences read slightly stiffly. Trade accepted.
- **Context-supply errors (Mechanism C).** When the dispatching prompt supplies a wrong frame, every model reviewer operates on the wrong frame and converges on a wrong answer. [`CROSS_MODEL_REVIEW_VALUE.md`](CROSS_MODEL_REVIEW_VALUE.md) documents this as a third class of failure that cross-model review explicitly does not catch — only human contextual review does. The worked example is that document's own v1 → v2 → v3 history: three model agents (gravel drafting v1, Codex validating v1, shale revising into v2) all accepted a consumer-subscription-pricing frame the dispatch prompt referenced; the human author caught the enterprise-vs-consumer pricing mismatch on first read of v2 and forced the v3 reframe. Cross-model review is one of three review layers, not the only one.

### Honest summary

The harness reduces the cost of producing a working software artifact by something in the 30-50× range against equivalent senior-engineer labor — see [`COST_METHODOLOGY.md`](COST_METHODOLOGY.md) for the per-hour reference comparison. It does not reduce the cost of taste, design judgment, or context that lives in a human's head. Both stay in the loop.

---

## 6. Companion utility

Geographica ships with an offline data pipeline (NAIP imagery acquisition, OSM POI extraction, elevation tile generation). The pipeline runs on the Pi 5 the stack is deployed to, but the work is CPU- and memory-bound: extracting and processing 8+ GB of NAIP TIFs against a 16 GB Pi takes hours and pushes the device near its memory ceiling. For a beta tester sitting on a faster workstation with a stable Internet pipe, the right ergonomic answer is to do the heavy work on the workstation and ship the resulting MBTiles to the Pi.

A separate cross-platform desktop utility (Geographica Companion) was built in a parallel repository to do exactly that. Same agent-team workflow as the main repo: brainstorm → multi-round adversarial review → plan → TDD execution by sub-agents. The pattern generalized cleanly across three significant differences from the main project: a different codebase (no shared code with the Pi stack), a different platform target (Windows + macOS + Linux desktop instead of Pi 5), and a different runtime model (long-running batch jobs invoked from a browser UI instead of always-on services behind nginx).

The companion's existence is itself a process artifact, not just a feature: it demonstrates that the agent-team workflow is not coupled to any one project's idioms or test harness. The receipts live in the companion's own repository with its own `dev/adversarial/`, `dev/implementation-log.md`, and `CHANGELOG.md`. Operational details — how to install, how to use, how to wire the SCP step into the Pi's data directory — live in [`MANUAL_SETUP.md`](MANUAL_SETUP.md), per the doc-split decision. This page carries only the *why* and the *origin*.

---

## 7. References

Every claim in this document points at on-disk artifacts. The index below lets a reader audit any of them directly.

### Process artifacts

- [`docs/superpowers/specs/`](superpowers/specs/) — 42 design specs, one per non-trivial feature. Each carries a revision history, locked design decisions, open questions, and cross-references to its adversarial-review round files.
- [`docs/superpowers/plans/`](superpowers/plans/) — 25 implementation plans. Each is a numbered task list with test-first acceptance criteria and review checkpoints between tasks.
- [`dev/adversarial/`](../dev/adversarial/) — 40+ committed adversarial-review files, named by date + topic + reviewer (e.g., `2026-04-25-cost-methodology-r5-codex.md`). Receipts for the multi-model review pattern in §3.
- [`dev/implementation-log.md`](../dev/implementation-log.md) — reverse-chronological log of significant work items: features shipped, bug-hunt cycles, adversarial reviews, and post-mortems. The narrative spine of the project.
- [`CHANGELOG.md`](../CHANGELOG.md) — user-visible release history, generated and maintained by the release-please workflow.

### Cost and methodology

- [`docs/COST_METHODOLOGY.md`](COST_METHODOLOGY.md) — full reasoning behind the two cost numbers in §1, the cache-write exclusion rationale, the cache-reads-as-harness-artifact argument, the corrections from the 2026-04-25 adversarial cycle, and reference comparisons to senior-engineer labor.
- [`docs/CACHE_OPTIMIZATION.md`](CACHE_OPTIMIZATION.md) — practices for reducing cache-read overhead in long Claude Code sessions; one paragraph cross-linked from `COST_METHODOLOGY.md`.
- [`docs/CROSS_MODEL_REVIEW_VALUE.md`](CROSS_MODEL_REVIEW_VALUE.md) — quantified ROI analysis for adding Claude API consumption on top of an existing Codex baseline; the recursive worked-example of the cross-model review pattern.
- [`scripts/audit_inference_cost.py`](../scripts/audit_inference_cost.py) — the audit script that produces the cost numbers. Can be re-run against any Claude Code project's transcript directory; reproduces this project's numbers ±1%.

### The artifact itself

- [`README.md`](../README.md) — what Geographica is, what it does, and how to install it.
- [`SETUP.md`](SETUP.md) — wizard happy-path, ~30 minutes from fresh Pi to working stack.
- [`MANUAL_SETUP.md`](MANUAL_SETUP.md) — advanced and recovery setup, including companion-utility operational details.
