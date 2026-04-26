# R1 — Math correctness review of cost methodology

**Reviewer:** wren
**Date:** 2026-04-25
**Scope:** scripts/audit_inference_cost.py + spec §4.2-4.3 + audit output reproducibility

---

## Findings

### CRITICAL

---

#### C1 — Opus 4.x pricing constants are wrong by 3x on output

**File:** `scripts/audit_inference_cost.py:21-25`

```python
PRICING = {
    "opus":   {"input": 15.0, "output": 75.0},   # WRONG
    ...
}
```

Anthropic's published rates for Claude Opus 4.5, 4.6, and 4.7 are **$5/M input, $25/M output** — not $15/$75. The $15/$75 rate applies to Claude Opus 4.0 and 4.1, which are not present in this corpus.

**Verification source:** https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching (pricing table, confirmed 2026-04-25 via WebFetch). Also confirmed by `npx ccusage` model pricing database (2684 models loaded). The prompt-caching doc explicitly lists:

| Model | Base Input | 5m Cache Write | 1h Cache Write | Cache Read | Output |
|-------|-----------|----------------|----------------|------------|--------|
| Opus 4.7 | $5/MTok | $6.25/MTok | $10/MTok | $0.50/MTok | $25/MTok |
| Opus 4.6 | $5/MTok | $6.25/MTok | $10/MTok | $0.50/MTok | $25/MTok |

**Corpus:** Production transcripts contain only `claude-opus-4-6` (20,603 turns) and `claude-opus-4-7` (16,128 turns). Zero turns from Opus 4.0 or 4.1. The wrong rate applies to 100% of Opus charges.

**Quantified impact** (against current corpus):

| Scenario | Headline (uncached) | Full list price |
|---|---:|---:|
| Current script ($15/$75, no dedup) | $2,272 | $19,907 |
| Correct pricing ($5/$25, no dedup) | $777 | $6,812 |
| **Overstatement factor** | **2.9×** | **2.9×** |

The cache-read cost is also overstated by 3× as a result: 0.10 × $15 = $1.50/M (applied) vs 0.10 × $5 = $0.50/M (correct). Over 8.7B Opus cache-read tokens, this alone inflates the full list price by $8,740.

**The spec §4.3 numbers ($2,489 headline / $21,858 full) were derived from these wrong rates** — they match neither the correct prices nor the current run. They appear to be pre-script estimates from a session where $15/$75 was assumed. Both spec figures must be replaced.

---

#### C2 — Output tokens are double-counted due to streaming partial records

**File:** `scripts/audit_inference_cost.py:59-81` (no message-ID deduplication)

Claude Code transcripts write multiple JSONL records per assistant response:
1. An intermediate streaming record (`stop_reason: null`, tiny `output_tokens` like 1-3 — the streaming "thinking" placeholder).
2. A final complete record (`stop_reason: tool_use` or `end_turn`, full `output_tokens`).

Both records carry the same `message.id`. The script sums every usage-bearing record without deduplication, so a response generating 232 output tokens is counted as ~235 (1 streaming + 234 final, or similar). Across the full corpus:

| Tier | Raw output tokens | Deduped output tokens | Overcounted | $ impact (correct pricing) |
|---|---:|---:|---:|---:|
| Opus | 29,701,766 | 14,955,603 | 14,746,163 | $368.65 |
| Sonnet | 1,619,492 | 1,585,154 | 34,338 | $0.52 |
| Haiku | 1,075,851 | 1,036,580 | 39,271 | $0.20 |

**Methodology verified:** Input tokens, cache creation tokens, and cache read tokens are **identical** across all occurrences of the same message ID — only `output_tokens` diverges. The first record always has a small partial count (stop_reason=null); the final record has the true billable count. Last-seen-per-msg_id, or max-per-msg_id, would correctly deduplicate.

**Combined impact of C1 + C2 together:**

| Scenario | Headline | Full list price |
|---|---:|---:|
| Current script (both errors) | $2,272 | $19,907 |
| Pricing fixed, dedup fixed | $405 | $3,707 |
| **Overstatement** | **5.6×** | **5.4×** |

Both errors must be fixed before the number is defensible. The spec's $2,489 and $21,858 figures are already in the README and methodology spec; both will need to change substantially when the script is corrected.

---

### MAJOR

---

#### M1 — model_tier() is too coarse to price different Opus generations correctly

**File:** `scripts/audit_inference_cost.py:28-38`

The function maps any model ID containing `"opus"` to a single "opus" bucket. This is incorrect because:
- Opus 4.0/4.1: $15/M input, $75/M output (the "legacy" rate)
- Opus 4.5/4.6/4.7: $5/M input, $25/M output (the "current" rate)

If the corpus ever contains a mix (e.g., a project that started on Opus 4.1 before the upgrade), both generations get the same rate — whichever is hardcoded. Fixing C1 by changing the constant to $5/$25 would then undercount any Opus 4.0/4.1 turns. The correct fix is per-model-ID pricing, not tier buckets:

```python
MODEL_PRICING = {
    "claude-opus-4-7": {"input": 5.0, "output": 25.0},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0},
    "claude-opus-4-1": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0},
    # ... with fallback-to-tier for unknown variants
}
```

Note: this project's corpus contains only Opus 4.6 and 4.7, so after fixing C1 to $5/$25, M1 does not affect this project's specific numbers — but the methodology claims to be a reusable script that "any reader can invoke on their own `~/.claude/projects/*/`", so correctness matters for the general case.

---

#### M2 — test_price_totals_opus_known_values validates the wrong pricing and is silent about it

**File:** `tests/test_audit_inference_cost.py:42-54`

```python
expected_full = (
    10 / 1e6 * 15       # Wrong rate — should be 5
  + 200 / 1e6 * 15 * 1.25
  + 800 / 1e6 * 15 * 2.0
  + 5000 / 1e6 * 15 * 0.10
  + 50 / 1e6 * 75      # Wrong rate — should be 25
)
```

The test directly mirrors the wrong constants from `PRICING`, so it passes regardless of whether the constants are correct. This is a test that proves the formula is internally consistent but cannot catch pricing errors. The test should instead assert against independently computed dollar amounts using the rate as a named constant with a comment citing the source URL and a date.

---

#### M3 — The spec's cost figures do not match the script's output at any pricing assumption

**File:** `docs/superpowers/specs/2026-04-25-readme-overhaul-design.md:62, 177-178`

The spec states:
- Headline number: $2,489
- Full list price: $21,858
- Cache reads: "8.1 B at $1.50/M = $12.1K"
- Cache writes: "110 M at $18.75–$30/M = $3.3K"

None of these match the current script output ($2,272 / $19,907 at wrong pricing), and none match correct pricing ($777 / $6,812). The spec numbers appear to be rough pre-script estimates written before the script produced any output, based on wrong $15/$75 Opus rates. The cache-read figure of "8.1B at $1.50/M" uses 0.10 × $15 = $1.50/M (wrong base rate); the correct rate is 0.10 × $5 = $0.50/M.

When the script is corrected, the README callout phrase "~$2,500 of API-equivalent model output" and the methodology page's "$2,489" headline must both be updated to the corrected figure (~$405 at current token counts after both fixes). The delta is large enough to change the narrative: the pitch changes from "~$2,500" to "~$400."

---

#### M4 — "Turns" column counts streaming records, not logical responses

**File:** `scripts/audit_inference_cost.py:81` (`totals[tier]["turns"] += 1`)

The script increments `turns` for every usage-bearing JSONL line. Because streaming emits 2–5 records per logical response (the ratio varies by tool-use complexity), the "Turns" figure in the output table is overstated by the same factor as output tokens. For Opus, the dedup ratio is 29.7M raw output → 15.0M deduped output (roughly 2× inflation). Calling these "turns" in the README summary table misleads readers about how many actual interactions occurred. The column should either be renamed "API records" or the counting logic should deduplicate by `message.id`.

---

### MINOR

---

#### m1 — Top-level cache_creation_input_tokens field is silently ignored

**File:** `scripts/audit_inference_cost.py:75-80`

The script reads `cache_w_5m` and `cache_w_1h` from `usage.cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`. Real transcripts also carry a top-level `usage.cache_creation_input_tokens` field. In every production transcript inspected, this field equals `ephemeral_5m + ephemeral_1h`, so the structured subtotals are complete. However, if the top-level field were ever populated without the nested struct (e.g., older API version or a future change), cache writes would be silently undercounted. A defensive check:

```python
# Sanity check: top-level vs structured sum
top_level_cc = usage.get("cache_creation_input_tokens", 0) or 0
struct_cc = cc.get("ephemeral_5m_input_tokens", 0) + cc.get("ephemeral_1h_input_tokens", 0)
# They should match; if not, fall back to top_level_cc for the sum
```

This is not a live bug on this corpus (0 mismatches found across 949 files), but is worth noting for methodology completeness.

---

#### m2 — server_tool_use charges ignored

**File:** `scripts/audit_inference_cost.py` (no reference to `server_tool_use`)

Real transcripts include `usage.server_tool_use.web_search_requests` and `usage.server_tool_use.web_fetch_requests`. Anthropic charges separately for server-side tool use. On this specific corpus, every turn shows zero web_search and zero web_fetch requests, so the current methodology is not missing any charges. However, the methodology page should explicitly note this exclusion so readers running the script on corpora that used web search aren't surprised by an undercount.

---

#### m3 — inference_geo "not_available" field is present but unexplained

All production usage objects include `"inference_geo": "not_available"`. Anthropic documents a 1.1× pricing premium for US-only inference when `inference_geo` is specified. The "not_available" value appears to be the default for Claude Max (non-API) sessions where routing is Anthropic-controlled. No 1.1× uplift applies here, but the methodology should acknowledge this assumption: the figures assume global-routing rates and would be 10% higher for workloads configured for US-only inference residency.

---

### Verified correct

1. **Cache multipliers are correct.** The 1.25× (5m write), 2.0× (1h write), and 0.10× (cache read) multipliers in `price_totals()` match Anthropic's published cache pricing exactly. Source: https://platform.claude.com/docs/en/docs/build-with-claude/prompt-caching, confirmed 2026-04-25.

2. **Sonnet 4.6 pricing is correct.** $3/M input, $15/M output matches Anthropic's published rate.

3. **Haiku 4.5 pricing is correct.** $1/M input, $5/M output matches Anthropic's published rate.

4. **Glob pattern covers all transcript files.** Verified by filesystem count: 50 parent `.jsonl` files at depth-1 + 899 subagent `.jsonl` files at `*/subagents/` = 949 total, matching `find ... -name '*.jsonl' | wc -l`. Zero `.jsonl` files exist outside these two patterns. The `*/subagents/*.jsonl` glob correctly captures all subagent sessions.

5. **None/null value handling is correct.** The `or 0` fallback on all `usage.get()` calls correctly coerces `None` to zero. No silent NaN propagation.

6. **Service tier is uniformly "standard".** All 54,846 usage-bearing records with a model ID show `service_tier: "standard"`. Zero batch-API turns. Standard-rate pricing is correct for the entire corpus.

7. **No `<synthetic>` turns are priced.** The 13 synthetic-model records have no tier match and are correctly excluded by `model_tier()`.

8. **Math formula for full/uncached is internally consistent.** Given the PRICING dict, the arithmetic in `price_totals()` is correct: input cost, cache write costs (5m and 1h), cache read cost, and output cost are each computed correctly and summed without any off-by-decimal-place or flipped multiplier errors.

9. **Directory layout matches the script's assumptions.** 43 session subdirectories each contain a `subagents/` folder. No `.jsonl` files exist at depth > 2 (i.e., no deeper nesting than `<sessid>/subagents/*.jsonl`).

---

## Recommendation

**Fix CRITICAL findings before ship.**

The headline number produced by the current script is wrong by 5.6× on the uncached figure and 5.4× on the full list price, due to the compound effect of wrong Opus pricing (C1) and output token double-counting (C2). Both must be corrected before any number appears in public documentation.

Minimum required fixes before the script's output can be cited:

1. **C1:** Change `PRICING["opus"]` to `{"input": 5.0, "output": 25.0}` — or, better, switch to per-model-ID pricing as described in M1 to future-proof for mixed corpora.
2. **C2:** Deduplicate by `message.id` before accumulating token counts; take the max (or last-seen) `output_tokens` per ID and the same-across-all `input_tokens`.
3. **Tests:** Update `test_price_totals_opus_known_values` to assert against the correct $5/$25 rates with a comment citing source URL + date.
4. **Spec:** Update the spec's `$2,489` and `$21,858` figures to the script's corrected output once both fixes land.
5. **Narrative:** The corrected headline (~$400, not ~$2,500) changes the pitch. The README callout "~$2,500 of API-equivalent model output" will need revision.

Two rounds of prior review (R3/framing, R5/Codex) identified both CRITICAL issues independently. This R1 review corroborates their findings with independent pricing verification and per-tier monetary quantification.
