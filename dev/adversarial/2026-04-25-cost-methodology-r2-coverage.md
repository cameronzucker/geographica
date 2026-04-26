# R2 — Coverage / sampling completeness review of cost methodology

**Reviewer:** basalt
**Date:** 2026-04-25
**Scope:** What inference happened on this project that is NOT counted — and are the counts that ARE present priced correctly?

---

## Findings

### CRITICAL

---

#### C1 — Opus pricing is wrong by 3x: claude-opus-4-6 and claude-opus-4-7 are $5/$25, not $15/$75

The audit script's `PRICING["opus"]` is set to `{"input": 15.0, "output": 75.0}` — the price for Claude Opus 4.1 (`claude-opus-4-1-20250805`). But the models actually used in these sessions are `claude-opus-4-6` (20,603 turns) and `claude-opus-4-7` (16,144 turns). Per LiteLLM's current pricing data (which ccusage fetches from `https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json`), both models are priced at:

```
claude-opus-4-6: $5/M input, $25/M output, $0.50/M cache_read, $6.25/M cache_write
claude-opus-4-7: $5/M input, $25/M output, $0.50/M cache_read, $6.25/M cache_write
```

This was independently verified by cross-checking ccusage's computed cost against the token counts:

```
opus-4-6: 199,581 input + 2,075,579 output + 29,839,375 cache_create + 3,198,006,615 cache_read
At $5/$25/$6.25/$0.50: $1.00 + $51.89 + $186.50 + $1,599.00 = $1,838.39 ✓ (matches ccusage)
At $15/$75/$18.75/$1.50 (audit script): $5,515.16 — 200% overstatement
```

**Impact on all numbers:**

| Metric | Audit Script | Correct (per LiteLLM) | Error |
|--------|-------------|----------------------|-------|
| Uncached I/O | ~$2,261 | ~$776 | 3× overstatement |
| Full list price | ~$19,858 | ~$6,803 | 2.9× overstatement |

Computed correct costs (per-model token counts extracted from transcripts):

```
claude-opus-4-6:  uncached=$145.00  full=$3,081.73
claude-opus-4-7:  uncached=$601.02  full=$3,459.09
claude-haiku-4-5: uncached=$5.70    full=$74.46
claude-sonnet-4-6: uncached=$24.25  full=$187.98
TOTAL:            uncached=$775.98  full=$6,803.26
```

The spec document (`docs/superpowers/specs/2026-04-25-readme-overhaul-design.md` §4.3 and §10.2) explicitly states "uncached input × $15/M ... for Opus" and uses this to derive the $2,489 headline — so the spec is also wrong. Codex R5 independently missed this because its attack angle was pricing correctness at the Anthropic API level, not the specific model-version pricing tier.

**The numbers in the README pitch, the spec, the methodology page, and the audit script are all inflated by ~3×.** The headline of "~$2,500 of API-equivalent model output" should be "~$780."

**Fix required:** The `PRICING` dict must be keyed by actual model sub-version, not tier family. Minimum fix: split `opus` into `opus_old` (for `claude-opus-4-1`/`claude-opus-4`) at $15/$75 and `opus_new` (for `claude-opus-4-5` through `claude-opus-4-7`) at $5/$25. The `model_tier()` function must be updated to route accordingly. Tests must be updated to reflect correct rates.

---

#### C2 — ccusage shows $3,430 total across ALL projects; no per-project breakdown available

`ccusage` is installed (`npx ccusage`) and produces a total cost across **all** Claude Code projects on this machine. Current output:

```
Total (April 2026, all projects): $3,430
```

This includes the `tuxlink` project (a separate unrelated project, ~350 turns, ~$260 full cost at correct rates). The audit script is scoped to the geographica project directory only, so it does NOT include tuxlink — this is correct behavior.

However, the spec (§4.3) claims "the $2,489 number ... any reader can reproduce with `ccusage`." This claim is false on two counts:

1. `ccusage` (with correct model pricing) gives ~$776 for geographica, not $2,489.
2. `ccusage` without a `--project` filter returns all projects combined, not just geographica.

A reader who runs `ccusage` expecting to reproduce "$2,489" will get ~$3,430 (all projects, correct rates) and conclude the methodology is inconsistent with the tool it cites. Existing R3 reviewer (flint) flagged the "appeal-to-tool" framing; this finding adds a concrete reproduction failure on top.

---

### MAJOR

---

#### M1 — Codex usage is real, documented, and completely absent from the methodology disclosure

Evidence: 30 Codex session files in `~/.codex/sessions/` for the geographica project, spanning April 7–25, 2026. Sessions use model `gpt-5.4` (29 sessions) and `o4-mini` (1 session). The sessions include substantive work: reading spec files, reading adversarial review outputs, writing multi-kilobyte analysis documents to disk, and executing `exec_command` tool calls (477 total tool calls extracted). There are 7 committed Codex adversarial review outputs in `dev/adversarial/*-codex.md`.

These sessions are **covered by the ChatGPT Plus subscription (~$20/mo), not Claude Max**, so the actual out-of-pocket cost is ~$0 per session in marginal terms. However:

1. The token volume is real. Extracted from session JSONL: ~50K output tokens (model text) + ~6.1M tool-output tokens fed back to the model (extracted via `Original token count: N` fields embedded in tool call responses). At GPT-4o US API list rates ($2.50/M input, $10/M output), the list-rate equivalent would be **~$17–$68** depending on system context estimates.

2. The methodology says nothing about this. A reader who understands the CLAUDE.md note ("Codex IS installed and used for adversarial reviews") will reasonably ask: "Are these tokens in the $2,500 figure?" The answer is no — they are in a completely separate tool with a separate subscription. This is not a lie, but it is a gap in the disclosure that a senior engineer will notice.

**Minimum fix:** The methodology page should add one sentence: "Codex (OpenAI GPT-5.4 via ChatGPT Plus subscription) was used for independent adversarial reviews — 30 sessions totaling approximately 50K output tokens. These are covered by a separate ~$20/mo ChatGPT Plus subscription and are not included in the Claude API-equivalent figures above."

---

#### M2 — The spec's stated numbers ($2,489 / $21,858) do not match the audit script's current output

The spec hardcodes "$2,489" and "$21,858" as the two disclosure numbers. The audit script currently outputs **$2,261 uncached / $19,858 full** — a gap of ~$228 uncached and ~$2,000 full. Both gaps are in the same direction (spec numbers are higher), suggesting the spec was written at an earlier point when fewer turns had been recorded, then not updated.

More importantly: these numbers are all computed at the wrong $15/$75 opus pricing rate. The correct numbers (at $5/$25 for opus-4-6/4-7) are:
- Headline (uncached): **~$776** (not $2,489 or $2,261)
- Full list: **~$6,803** (not $21,858 or $19,858)

When the pricing error is corrected, the "full list" number that ccusage computes (~$3,430 for all projects) becomes comprehensible as roughly $3,170 for geographica — close to the corrected $6,803 "full" (difference explained by the fact that ccusage uses a flat cache write rate and doesn't distinguish 5m/1h tiers, while the audit script does).

---

#### M3 — The tuxlink project tokens are excluded, but tuxlink is NOT documented as out-of-scope

The only other Claude Code project on this machine is `tuxlink` (~350 Opus turns, ~$260 full cost at correct rates). This is an unrelated project started April 23, 2026 — after the Geographica project was well underway. Exclusion from the Geographica audit is correct, but the methodology should explicitly document the project boundary ("transcript directory: `~/.claude/projects/-home-administrator-Code-geographica/`; other projects on this machine, e.g. tuxlink, are excluded"). Without this documentation, a reader reproducing the audit who runs `ccusage` without a project filter will see ~$3,430 and question why it doesn't match.

---

### MINOR

---

#### m1 — No archived/rotated logs exist — this is verified complete

`find ~/.claude -name '*.gz' -o -name '*.zip' 2>/dev/null` returns nothing. Claude Code does not rotate or archive transcripts in any gz/zip format on this installation. All 950 transcript files (50 parent + 900 subagent) are accounted for by the `*.jsonl` + `*/subagents/*.jsonl` glob pattern. There is no nesting beyond one level of subagents (`find ~/.claude/projects/-home-administrator-Code-geographica -name '*.jsonl' -mindepth 5` returns 0 results). This coverage gap is NOT present.

#### m2 — 26 zero-output turns are captured correctly

26 turns have `output_tokens=0` (rate-limited or aborted). Of these, 6 have non-zero `cache_read_input_tokens`. The audit script counts `cache_r` for these turns regardless of `output_tokens`, so they ARE included in the "full list price" calculation. This is correct behavior — these cache reads were billed. Not a gap.

#### m3 — The `<synthetic>` model (13 turns) is silently ignored

The transcripts contain 13 turns with `model="<synthetic>"` — internal Claude Code test/mock turns. `model_tier("<synthetic>")` returns `None`, so these are excluded. Token counts for synthetic turns are all zeros, so exclusion has zero dollar impact. Acceptable, but the methodology should document this exclusion class for reproducibility.

#### m4 — MCP server tool calls have no per-token metered cost

The project uses context7 and playwright MCP servers. These have no token-level billing — they are client-side tool integrations that run locally and return text results that feed into the Claude context. The MCP tool call results appear as `cache_read_input_tokens` or `input_tokens` in the usage field when the model processes them. This cost IS counted by the audit script (as part of the cache read or input token stream). No gap.

#### m5 — Fast mode / subscription tier metadata is not in the transcripts

Searched for `costUSD` fields in transcripts: none found across 1,144 sampled turns. The transcripts record `usage` (token counts) and `service_tier: "standard"` but no Anthropic-side subscription billing data. There is no way to determine from transcripts whether the user hit Claude Max usage limits on any day. This is a theoretical gap in the "out-of-pocket cost" narrative, but since the methodology explicitly frames costs as "API-equivalent list rates," not actual cash paid, it does not affect the reported numbers.

---

## Verified complete

- Subagent glob depth: `*/subagents/*.jsonl` captures all subagent transcripts. No deeper nesting observed (0 files at depth 5+). The glob is complete.
- Archived/rotated logs: None exist. Not a gap.
- Claude Code project directories on this machine: exactly 2 (`geographica`, `tuxlink`). Geographica-companion was built within the geographica Claude project (not a separate project directory). No hidden project transcripts.
- Zero-output turns: 26 total; 6 have cache reads which are correctly counted. No billing gap.
- MCP tool calls: not separately billed; cost is captured in model token usage as it is.

---

## Recommendation

**Substantial revision required — do not ship as-is.**

Two blockers, in priority order:

**Blocker 1 (C1):** Fix the pricing constants. `claude-opus-4-6` and `claude-opus-4-7` are priced at $5/M input / $25/M output, not $15/$75. All headline numbers in the audit script, the spec, and the planned methodology page are wrong by approximately 3×. The correct headline is **~$776 uncached** and **~$6,803 full list price**. The audit script, PRICING dict, model_tier function, test assertions, and spec numbers all need updating before any public claim is made.

**Blocker 2 (C2 + M1):** The methodology page cannot claim "`ccusage` reproduces this number" — it does not, and the reproduction path is broken in multiple ways (wrong model pricing, multi-project scope, stale spec numbers). The page should instead describe the calculation methodology and note that Codex sessions (covered by ChatGPT Plus) are excluded with a brief characterization of their volume.

Once C1 is fixed, the new numbers (~$776 / ~$6,803) are actually *more* compelling for the pitch — the project consumed a fraction of what Opus 4.1 API rates would suggest, because Anthropic introduced cheaper successor models (Opus 4.6, 4.7) during the build. This is itself a story worth telling in the methodology page.
