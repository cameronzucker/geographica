# Cost methodology

> Honest accounting of what Geographica's AI-orchestrated build cost in inference. Two numbers are reported because two different questions deserve answers; both are derived from the same on-disk transcript data and the audit script that ships with this repo.

This document is the long-form companion to the cost callout in [`README.md`](../README.md). It exists to satisfy the skeptical reader who wants to know exactly what was counted, what was excluded, and why.

A separate document, [`CACHE_OPTIMIZATION.md`](CACHE_OPTIMIZATION.md), discusses what could have been done to reduce the full list price further; it is referenced from §9 below.

---

## 1. Headline number — ~$284 (uncached input + output, at API rates)

The headline figure represents what the model actually generated: input tokens it ingested plus output tokens it produced, priced at Anthropic's published per-model API rates.

Per-model breakdown (snapshot 2026-04-25):

| Model            | Responses | Uncached I/O ($) |
|------------------|----------:|-----------------:|
| claude-haiku-4-5 |     4,602 |             1.81 |
| claude-opus-4-6  |    12,082 |            52.89 |
| claude-opus-4-7  |     8,034 |           220.72 |
| claude-sonnet-4-6|     5,049 |             9.00 |
| **Total**        |           |       **284.42** |

Per-model rates used (Anthropic published, 2026-04):

| Tier   | Models                    | Input ($/M) | Output ($/M) |
|--------|---------------------------|------------:|-------------:|
| Opus   | 4.5 / 4.6 / 4.7           |        5.00 |        25.00 |
| Sonnet | 4 / 4.5 / 4.6             |        3.00 |        15.00 |
| Haiku  | 4.5                       |        1.00 |         5.00 |

**Convention.** Uncached input plus output is the same convention used by the community tool [`ccusage`](https://github.com/ryoppippi/ccusage). It is not an Anthropic-endorsed definition of "model work" — Anthropic is the authority on its own billing, not a third-party tool. The convention is named here so a reader who has seen `ccusage` numbers will recognize the framing; it is not used as a validation step. The audit script ships with this repository so the calculation can be inspected and challenged directly.

**Footnote — snapshot freshness.** The numbers above were captured 2026-04-25 with the corrected audit script (commit `e456666`) against the project's transcript directory. They drift upward as the project remains active. To regenerate against the current state of the transcripts, run `scripts/audit_inference_cost.py` (see §7); the numbers will be larger but proportionally similar.

---

## 2. Full list-price number — ~$3,593 (everything Anthropic would bill at API list)

The full list-price figure adds two further token categories that appear on Anthropic's API bill: cache reads and cache writes.

Per-model breakdown (same snapshot, 2026-04-25):

| Model            | Responses | Uncached I/O ($) | Full list price ($) |
|------------------|----------:|-----------------:|--------------------:|
| claude-haiku-4-5 |     4,602 |             1.81 |               33.40 |
| claude-opus-4-6  |    12,082 |            52.89 |            1,916.36 |
| claude-opus-4-7  |     8,034 |           220.72 |            1,545.16 |
| claude-sonnet-4-6|     5,049 |             9.00 |               97.80 |
| **Total**        |           |       **284.42** |        **3,592.72** |

Cache pricing applied (per Anthropic published rates):

- **Cache reads:** 0.10× the model's input rate (e.g. Opus reads at $0.50/M)
- **Cache writes (5-minute ephemeral):** 1.25× the model's input rate
- **Cache writes (1-hour ephemeral):** 2.0× the model's input rate

**Cache reads are 49% of the full list price; cache writes are another 43%.** Together, cache-related charges are ~92% of what would appear on a hypothetical API invoice. The reason these charges are large is structural: Claude Code reloads a large persistent context (~250K–340K tokens per turn) to maintain agent memory across a session, and that context accumulates cache-read charges proportional to session length and context size — not to the complexity of the work being requested.

**The argument that cache reads measure harness behavior, not work output.** A Claude Code session doing trivial edits accumulates the same cache-read cost per turn as one writing complex algorithms, because the context window is the same. Cache reads are charged by Anthropic — which is why they appear in the full list price — but they are a function of *how* the agent harness manages context, not a function of *what* the agent produced. Switching harnesses (or trimming the harness's system prompt) would reduce cache reads without affecting the work output. This is the principled basis for separating them from the headline. Readers who consider context-management overhead part of the cost should use the $3,593 figure; readers measuring productive generation should use the $284 figure.

---

## 3. Why exclude cache writes from the headline

Cache writes are real, billable tokens that the model processed at full rate. The Anthropic API charges for them; the `cache_creation` field in the API's usage object is a line item on the bill, not advisory. Excluding them from the headline without explicit reasoning would look like cherry-picking — and a reader applying the methodology's own stated standard ("what did the model actually generate?") might reasonably expect them to be included.

The principled basis for the exclusion: **cache writes scale with context window size, not with the new work requested in each turn.** A session that re-loads the same 100K-token codebase 50 times accumulates the same cache-write cost regardless of whether it produces one line or 10,000 lines of output. Cache writes price the act of *creating* a cached representation so subsequent turns can read it cheaply; they are part of context-management overhead, not productive generation. They are kept out of the headline for the same reason cache reads are kept out: both measure harness behavior on a fixed context, not the volume or complexity of generated output.

They are not hidden. They appear in §2's full list price, and the per-model breakdown there can be inspected line by line. The headline number does not pretend they don't exist; it answers a different question.

---

## 4. What was actually paid

The figures above are list-rate equivalents — what Anthropic *would* have charged at full API pricing. The actual cash outlay was different:

- **Claude Max subscription:** ~$200/mo for one month (the subscription absorbs all of the above usage, well below subscription caps).
- **Codex (OpenAI), via ChatGPT Plus:** ~$20/mo. Codex was used for adversarial review rounds (see [`PROCESS.md`](PROCESS.md#section-3-adversarial-review-patterns) — the "Codex catches what 4 Claudes miss" pattern). Approximately 30 sessions across the project produced ~50K output tokens; list-rate equivalent ~$17–68 (negligible against the headline). Disclosed for completeness; not included in the Anthropic-billed figures above because they are billed separately.
- **Hardware:** Raspberry Pi 5 plus SSD (see the README hardware section for current specifications). Excluded from inference-cost figures by intention; hardware ages independently of model spend and does not belong in a per-month cost figure.

Combined subscription cost across both providers: ~$220 for the development month.

---

## 5. Why two numbers, not one

The two figures answer two different questions. Neither is the "real" cost to the exclusion of the other.

| Question                                                     | Number                | Use it to compare…                                  |
|--------------------------------------------------------------|-----------------------|-----------------------------------------------------|
| *What did the model actually generate?*                      | **~$284** (uncached)  | Productive output across projects or workflows.     |
| *What would this cost at full API list, no subscription?*    | **~$3,593** (full)    | Subscription value, or a hypothetical API-billed run. |
| *What was paid out of pocket?*                               | **~$220** (one month) | Real-dollar cost.                                   |

Reporting only the headline would understate the workload Anthropic absorbed under the subscription. Reporting only the full list would conflate work output with context-management overhead. Reporting both, with the rationale for the split, is what the rest of this page does.

---

## 6. Reference comparisons

A bare cost number invites the reader to anchor on the wrong reference class. The following comparisons are not part of the audit; they are scope-setting.

- **Senior-engineer labor for an equivalent build:** A 6-month feature-equivalent project at $100K/yr base = ~$50K labor; with benefits and overhead at 1.3–1.5× = **~$65,000–$75,000 loaded labor cost**.
- **Off-the-shelf GIS license:** ArcGIS Pro starts at ~$1,500/yr; ArcGIS Enterprise is in the **$5,000–$20,000/yr** range, plus integration labor.
- **Claude Max subscription:** **~$200/mo** for the development period.

Against the loaded-labor baseline, the inference figures (whether headline $284 or full list $3,593) represent productivity leverage at the order of magnitude of 20–250× — and the cash subscription cost is at the order of 0.3% of the labor baseline. These are not apples-to-apples replacements (an AI agent team is not a senior engineer; the project benefited from existing OSS components, prior art, and the subscription's burst capacity), but they are the comparisons the figures are most naturally measured against.

---

## 7. Reproduction (and its limits)

The audit script is at [`scripts/audit_inference_cost.py`](../scripts/audit_inference_cost.py). It reads a Claude Code project transcript directory, deduplicates by `(file, message.id)`, prices each response at the appropriate per-model rate, and emits a per-model breakdown.

```bash
python3 scripts/audit_inference_cost.py ~/.claude/projects/<project-slug>/ --markdown
```

**What can be reproduced.** Cameron can re-verify the numbers in this document at any time by re-running the audit script against the project's transcript directory at `~/.claude/projects/-home-administrator-Code-geographica/`. The script ships with unit tests against synthetic fixtures (see `tests/test_audit_inference_cost.py`) so the calculation itself can be inspected and challenged.

**What cannot be reproduced by an external auditor.** The transcript data is private to the user's local Claude Code install. A reader of this document cannot independently verify the $284 / $3,593 figures from first principles, because the underlying transcripts are not (and cannot be) published. What a reader *can* do is run the same script against their own `~/.claude/projects/<slug>/` directory and audit their own costs using the same methodology. That is the form of reproducibility this document offers; it is honest about the asymmetry.

---

## 8. Methodology corrections (post-audit transparency)

The numbers in this document survived a 4-reviewer adversarial cycle on 2026-04-25 that surfaced two CRITICAL math bugs in the original audit script. Both bugs inflated the cost figures; the corrections reduced the reported numbers substantially.

- **Per-line summing inflated counts ~1.85×.** Claude Code emits multiple JSONL lines per assistant response (one per content block: thinking, text, tool_use, tool_result), all carrying the same `message.id` and the same `usage` payload. The original script summed each line's `usage`, double-counting most responses. The fix deduplicates by `(file, message.id)`.
- **Wrong Opus pricing inflated Opus costs ~3×.** The original script hard-coded Opus rates at $15/M input / $75/M output (legacy Opus 4.0 / 4.1 rates). Anthropic's published rates for Opus 4.5 / 4.6 / 4.7 — the models actually used in this project — are $5/M input / $25/M output. The fix updates `PRICING_BY_MODEL` to the correct per-version rates.

Combined, the bugs caused a ~6–8× overstatement. The original draft reported figures around $2,489 uncached and $21,858 full list; the corrected snapshot reports $284 uncached and $3,593 full list. The full chronology — including the parallel-Sonnet review rounds that flagged the issues structurally and the Codex round that caught the mechanistic root causes — is in [`PROCESS.md` §3](PROCESS.md#section-3-adversarial-review-patterns).

This section exists to make a single point: the methodology has been pressure-tested by adversarial review, not just asserted. If a future reader finds another bug, that reader is invited to file an issue or a pull request against the audit script.

A minor exclusion is also documented for completeness: ~13 transcript turns use an internal `<synthetic>` model (a Claude Code test/mock model) with all-zero token counts. The audit script reports the unknown model name in its output but the responses contribute nothing to the dollar figures.

---

## 9. The cache-optimization aside

The full list price is dominated by cache-related charges (~92%). It is reasonable to ask: could the practices that produced this project have driven that lower?

The short answer is yes — and the long answer is in [`CACHE_OPTIMIZATION.md`](CACHE_OPTIMIZATION.md). That document examines six practices: subagent delegation and smaller-model selection (both applied here, with measurable effect), and four further practices that were considered but not applied (with stated rationale for each). The aggregate analysis suggests a "fully optimized" run of the same project could have landed near ~$1,200 full list price rather than ~$3,593, a roughly 65% reduction.

The reduced figure does not change the headline. The ~$284 headline is what the model actually generated; cache optimization affects context overhead, not work output. But for readers thinking about transferring the technique to higher-volume settings — where the subscription model no longer absorbs the bill — the cache-optimization practices are where the leverage lives.

The $3,593 is what was actually consumed under this project's chosen tradeoffs. It is not what was minimum-possible. Both facts deserve to be on the record.
