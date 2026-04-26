"""
Audit inference cost for a Claude Code project.

Reads ~/.claude/projects/<project-slug>/ (parent transcripts at top level,
subagent transcripts in <sessid>/subagents/) and prices each model at
Anthropic's published per-token rates.

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

# Anthropic published rates as of 2026-04 (verified against
# https://platform.claude.com/docs/en/about-claude/pricing).
PRICING_BY_MODEL = {
    'claude-opus-4-7':   {'input':  5.0, 'output': 25.0},
    'claude-opus-4-6':   {'input':  5.0, 'output': 25.0},
    'claude-opus-4-5':   {'input':  5.0, 'output': 25.0},
    'claude-opus-4-1':   {'input': 15.0, 'output': 75.0},
    'claude-opus-4':     {'input': 15.0, 'output': 75.0},
    'claude-sonnet-4-6': {'input':  3.0, 'output': 15.0},
    'claude-sonnet-4-5': {'input':  3.0, 'output': 15.0},
    'claude-sonnet-4':   {'input':  3.0, 'output': 15.0},
    'claude-haiku-4-5':  {'input':  1.0, 'output':  5.0},
}

# Cache multipliers — same across all models per Anthropic docs
CACHE_WRITE_5M_MULTIPLIER = 1.25  # 1.25× input rate
CACHE_WRITE_1H_MULTIPLIER = 2.0   # 2× input rate
CACHE_READ_MULTIPLIER     = 0.10  # 0.10× input rate


def normalize_model(model_id):
    """Normalize a model ID to its canonical form for pricing lookup.

    Strips:
    - context-window suffixes like [1m]
    - date suffixes like -20251001 (8-digit YYYYMMDD)

    Returns the canonical model ID if found in PRICING_BY_MODEL, else None.
    """
    if not model_id:
        return None
    m = model_id.lower().split('[')[0]  # strip [1m] etc.
    parts = m.split('-')
    # Strip 8-digit date suffix
    if len(parts) >= 4 and parts[-1].isdigit() and len(parts[-1]) == 8:
        m = '-'.join(parts[:-1])
    if m in PRICING_BY_MODEL:
        return m
    # Try shorter prefixes for partial matches (e.g., 'claude-opus-4-7-foo' → 'claude-opus-4-7')
    parts = m.split('-')
    while len(parts) > 2:
        candidate = '-'.join(parts)
        if candidate in PRICING_BY_MODEL:
            return candidate
        parts.pop()
    return None


def aggregate_directory(directory, parent_glob="*.jsonl", subagent_glob="*/subagents/*.jsonl"):
    """Sum token counts per assistant response across parent and subagent transcripts.

    Each assistant response in a Claude Code transcript may emit multiple JSONL
    lines (one per content block: thinking, text, tool_use, tool_result), all
    carrying the same `message.id` and the same `usage` payload. This function
    deduplicates by (filepath, message.id) so each response is counted once.

    Lines without a `message.id` are skipped (cannot be safely deduplicated).

    parent_glob:    glob pattern (relative to directory) for parent transcripts
    subagent_glob:  glob pattern for subagent transcripts; pass "" to disable
    """
    directory = Path(directory)
    files = sorted(directory.glob(parent_glob))
    if subagent_glob:
        files += sorted(directory.glob(subagent_glob))

    seen = set()
    totals = defaultdict(lambda: defaultdict(int))
    unknown_models = set()

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
                    msg_id = msg.get("id")
                    if not msg_id:
                        continue  # skip lines without ID — can't safely dedup
                    key = (str(fp), msg_id)
                    if key in seen:
                        continue
                    seen.add(key)

                    model_key = normalize_model(msg.get("model"))
                    if model_key is None:
                        unknown_models.add(msg.get("model"))
                        continue

                    cc = usage.get("cache_creation") or {}
                    t = totals[model_key]
                    t["input"]      += usage.get("input_tokens", 0) or 0
                    t["cache_w_5m"] += cc.get("ephemeral_5m_input_tokens", 0) or 0
                    t["cache_w_1h"] += cc.get("ephemeral_1h_input_tokens", 0) or 0
                    t["cache_r"]    += usage.get("cache_read_input_tokens", 0) or 0
                    t["output"]     += usage.get("output_tokens", 0) or 0
                    t["responses"]  += 1
        except OSError:
            continue
    return {k: dict(v) for k, v in totals.items()}, sorted(unknown_models)


def price_totals(totals):
    """Return per-model {full, uncached} cost in USD."""
    priced = {}
    for model, t in totals.items():
        p = PRICING_BY_MODEL[model]
        full = (
            t.get("input", 0)      / 1e6 * p["input"]
          + t.get("cache_w_5m", 0) / 1e6 * p["input"] * CACHE_WRITE_5M_MULTIPLIER
          + t.get("cache_w_1h", 0) / 1e6 * p["input"] * CACHE_WRITE_1H_MULTIPLIER
          + t.get("cache_r", 0)    / 1e6 * p["input"] * CACHE_READ_MULTIPLIER
          + t.get("output", 0)     / 1e6 * p["output"]
        )
        uncached = (
            t.get("input", 0)  / 1e6 * p["input"]
          + t.get("output", 0) / 1e6 * p["output"]
        )
        priced[model] = {"full": full, "uncached": uncached}
    return priced


def render_markdown(totals, priced):
    """Return a markdown table summarizing totals + prices."""
    lines = [
        "| Model | Responses | Uncached I/O ($) | Full list price ($) |",
        "|-------|----------:|-----------------:|--------------------:|",
    ]
    grand_unc = grand_full = 0.0
    for model in sorted(totals):
        t = totals[model]
        p = priced[model]
        lines.append(
            f"| {model} | {t.get('responses',0):,} "
            f"| {p['uncached']:,.2f} | {p['full']:,.2f} |"
        )
        grand_unc += p["uncached"]
        grand_full += p["full"]
    lines.append(
        f"| **Total** |  | **{grand_unc:,.2f}** | **{grand_full:,.2f}** |"
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", help="Project transcript directory")
    parser.add_argument("--markdown", action="store_true", help="Output markdown table")
    args = parser.parse_args()

    totals, unknown = aggregate_directory(args.directory)
    priced = price_totals(totals)

    if args.markdown:
        print(render_markdown(totals, priced))
        if unknown:
            print(f"\nUnknown models (not in pricing table): {', '.join(sorted(unknown))}")
        return

    # Plain-text breakdown
    print(f"Audit of {args.directory}\n")
    grand_full = grand_unc = 0.0
    for model in sorted(totals):
        t = totals[model]
        p = priced[model]
        print(f"  {model:<20} responses={t.get('responses',0):>6,d}  "
              f"uncached=${p['uncached']:>9,.2f}  full=${p['full']:>9,.2f}")
        grand_full += p["full"]
        grand_unc  += p["uncached"]
    print(f"  {'TOTAL':<20}            "
          f"uncached=${grand_unc:>9,.2f}  full=${grand_full:>9,.2f}")

    if unknown:
        print(f"\nUnknown models (not in pricing table — add entries to PRICING_BY_MODEL):")
        for m in sorted(unknown):
            print(f"  {m}")


if __name__ == "__main__":
    main()
