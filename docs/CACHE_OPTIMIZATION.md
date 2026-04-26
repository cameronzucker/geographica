# Cache optimization for Claude-Code-class agent harnesses

This document accompanies [`COST_METHODOLOGY.md`](COST_METHODOLOGY.md). It exists because the cost methodology raises an obvious question: *if cache cost is 92% of the full list price, why not optimize it?* The answer requires a tradeoff analysis that is too long for the methodology page itself.

## 1. Why cache cost dominates the full list price

Geographica's full inference audit (2026-04-25 snapshot, deduplicated, per-model pricing):

| Component | Cost | Share |
|---|---:|---:|
| Cache reads | ~$1,750 | 49% |
| Cache writes (5m + 1h) | ~$1,560 | 43% |
| Output tokens (model "work") | ~$280 | 8% |
| Uncached input | ~$3 | <1% |
| **Total full list** | **~$3,593** | |
| (of which subagent Sonnet+Haiku) | ~$132 | 3.7% |

Cache reads + writes together are 92% of the full list price. They come from Claude Code re-loading the system prompt, tool definitions, hooks, files-in-scope, and conversation history on every conversational turn (~250K-340K tokens per turn × ~30K unique responses).

The "headline" cost number — ~$284 — is the bottom three rows: actual generation work plus tiny uncached input plus subagent work. The cache rows are infrastructure overhead introduced by how Claude Code manages context. Everything in this document is about reducing the cache rows without touching the headline rows.

Even at the corrected (smaller) total, the cache portion remains dominant. The optimization story is the same shape; only the absolute numbers are smaller.

## 2. What was done

### Subagent delegation (highest-leverage practice applied)

Subagents in Claude Code run with isolated context — a fresh system prompt and only the parameters the parent passed in, not the parent's accumulated conversation history. This makes them dramatically cheaper per equivalent unit of work.

The receipts:

| Stream | Responses | Total cost (full list price) | Cost per response |
|---|---:|---:|---:|
| Parent Opus 4.6/4.7 sessions | ~20,100 | ~$3,461 | $0.172 |
| Subagent Sonnet 4.6 sessions | ~5,049 | ~$98 | $0.019 |
| Subagent Haiku 4.5 sessions | ~4,602 | ~$33 | $0.007 |

A Sonnet subagent response is **~9× cheaper** than a parent Opus response. A Haiku subagent response is **~24× cheaper**. The reduction comes from two compounding effects: (1) cheaper model per token (3-5× across tiers), (2) far smaller per-response context (subagents do not carry the parent's bloat).

Geographica's plan-and-execute pattern is built around this. Plans are decomposed so each task can be dispatched to a fresh subagent that needs only the task description and a few file paths. The result: ~32% of all responses ran in subagents at ~3.7% of total cost.

### Smaller-model selection for execution work

Within the subagent pool, model choice matters. Sonnet for tasks that need code understanding (~$98); Haiku for tasks that are purely mechanical (~$33). Opus is reserved for the controller and for architecture-level tasks where reasoning quality dominates.

Compare to a hypothetical "Opus everywhere" project: those ~9,651 subagent responses at parent-Opus rates would have cost roughly **20× more** — adding ~$2,500 to the total. The split of "Opus for thinking, Sonnet/Haiku for doing" saved a meaningful fraction of total cost without measurable quality loss.

## 3. What was not done (and why)

These practices would further reduce the full list price but were skipped for the reasons noted. Each entry has an estimated impact and an explicit tradeoff so the decision reads as deliberate.

### A. Aggressive manual `/compact`

Claude Code auto-compacts conversation history when the context window approaches its limit. Manual `/compact` could be invoked earlier, more aggressively. Doing so would reduce the per-response cached-prior-conversation volume.

- **Estimated impact:** 10-20% reduction in cache-read volume on long-running sessions, mostly affecting brainstorm and spec-review sessions where conversation history grows large. On the corrected $3,593 full price, this is ~$200-400.
- **Why not applied:** Compaction loses subtle context. The brainstorm sessions that produced the highest-quality specs depended on holding the full conversation in context — early decisions, why they were made, what was rejected. Compacting mid-brainstorm produced observably worse spec output in early experiments. The decision was made to take the cache cost rather than compromise spec quality.

### B. Lean system prompt

Claude Code's per-turn system prompt is large — bundled tool definitions, hooks, skill metadata, project CLAUDE.md, AGENTS.md, plugin context. Aggregate ~30K tokens, present on every turn. Most of those tokens are not used by most turns.

- **Estimated impact:** 30-50% reduction in cache-read volume across all sessions. On $3,593, this is ~$500-900.
- **Why not applied:** Modifying the harness's system prompt is invasive. Tool definitions cannot be removed without breaking the tools. Skill metadata is needed to determine which skills can be invoked. CLAUDE.md is intentionally always-on (it encodes project policy that every turn should respect). The trim opportunities are real but require modifying Claude Code itself, not user-side configuration.
- **Where this would land if applied:** outside this project's scope. Documenting it here means a future high-stakes user of this technique might choose a leaner harness for the savings.

### C. Shorter sessions / more frequent context reset

Each Claude Code session accumulates cached conversation history. Splitting work into more, shorter sessions resets that accumulation more often.

- **Estimated impact:** 10-20% reduction in average cache-read volume per response. ~$200-400 on this project's total.
- **Why not applied:** Cross-task context informs better decisions. A session that has just spent 20 turns understanding the codebase is more reliable on the 21st turn than a fresh session would be. The "do related work in one session" pattern is a quality choice, not laziness about cost.

### D. Different model for high-volume planning work

The brainstorm + spec + adversarial-review sessions consumed the largest share of Opus parent-stream responses (~13K of 20K). Running early-stage brainstorm on Sonnet (3-5× cheaper input) instead of Opus could cut planning-stream cache cost by ~70-80%.

- **Estimated impact:** ~$1,500 reduction in full list price (from $3,593 to ~$2,100).
- **Why not applied:** Spec quality on Sonnet is observably worse for novel problem domains. The brainstorm-then-adversarial-review pattern is most effective when the brainstorm itself is high-quality; spending more on the upstream investment pays off in fewer adversarial-review iterations downstream. The 2026-04-25 cost-methodology adversarial cycle is itself a worked example: 4 review rounds + script rewrite × 2 caught a $20K-equivalent error before it landed in front of decision-makers.

## 4. Aggregate impact estimate

If practices A, B, C, and D were applied to the maximum extent compatible with quality:

| Scenario | Estimated full list price |
|---|---:|
| As shipped (this project) | ~$3,593 |
| + Selective `/compact` (practice A, partial application) | ~$3,250 |
| + Lean system prompt (practice B, would require harness mod) | ~$2,400 |
| + Shorter sessions for mechanical work (practice C) | ~$2,000 |
| + Sonnet brainstorm where domain permits (practice D) | ~$1,200 |

A "fully optimized" version of this same project, with all practices applied where compatible with quality, would land near **~$1,200 full list price** — roughly a **65% reduction**. The headline number (~$284) is largely unchanged because that is actual model work, not cache overhead.

The honest framing for the cost methodology: **the ~$284 headline is what was earned in model output; the ~$3,593 full list is what Anthropic would have charged for the workload as run; the ~$1,200 figure is what Anthropic would have charged for the same shipped output if the harness were tuned for cost.** All three are defensible numbers; they answer different questions.

For this project specifically, the absolute savings ($2,000-$2,500) are not significant against a Claude Max subscription that absorbs all of it. But the *practices* are what matter at scale: a team running 100 Geographica-equivalent projects per year would convert ~$200K of optimization headroom from "fine, the subscription covers it" to "the subscription is the bottleneck."

## 5. Why this matters for transferring the technique

For a team or organization considering AI-orchestrated development at higher scale, the cost calculus generalizes:

- **Subagent delegation is the highest-leverage practice.** Not optional. Every project should be planned with subagent-decomposable tasks. On Geographica, this single practice is responsible for keeping the subagent share at 3.7% of total cost despite running 32% of all responses.
- **Model selection within the subagent pool is the second-highest lever.** A team that routes execution work to Sonnet/Haiku rather than Opus saves ~70-80% of subagent cost without measurable quality loss on most tasks.
- **The remaining cost-reduction practices are quality-bound.** They have real savings but trade off against output quality. The right ratio depends on what is being built — code review needs full context (do not compact), bug-fix runs do not (compact aggressively).
- **Subscription pricing changes the math entirely.** Claude Max at ~$200/mo absorbs the full list price up to a usage cap. For solo or small-team use, the subscription model means cost-optimization practices are about staying inside the cap rather than minimizing per-token spend. For large-team API usage, they are about minimizing the bill.
- **At small project scale, optimization is a write-down on subscription headroom, not cash savings.** The practices documented above do not make Geographica cheaper to produce — the Max subscription already covers it. They matter when running enough Geographica-equivalent projects to start hitting subscription caps or moving to API billing.

## 6. Reproducing the audit

The script that produced these numbers is at [`scripts/audit_inference_cost.py`](../scripts/audit_inference_cost.py). It runs against any `~/.claude/projects/<slug>/` directory and reports both the headline (uncached I/O) and full (with cache) numbers, broken down per model.

```bash
python3 scripts/audit_inference_cost.py ~/.claude/projects/<slug>/ --markdown
```

Compare a project that follows these practices against one that does not to quantify the impact for any given codebase. The script ships with unit tests against synthetic transcript fixtures (see `tests/test_audit_inference_cost.py`) so the calculation can be inspected and challenged.

The methodology page at [`COST_METHODOLOGY.md`](COST_METHODOLOGY.md) documents the audit's known limits and the 2026-04-25 adversarial-review cycle that produced the current numbers. Significant attention has been paid to the disclosure surface; if a number here looks wrong, please file an issue.
