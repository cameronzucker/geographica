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

    Subagent directories are discovered by correlating each matched parent
    file's stem to a same-named subdirectory: ``<stem>/subagents/*.jsonl``.
    This prevents cross-contamination when a specific parent_glob is passed
    (e.g. in tests) while still collecting the right subagents in production
    where parent files are named by session UUID.

    ``subagent_glob`` is accepted for API compatibility but is ignored in
    favour of the stem-correlation approach; pass ``subagent_glob=None`` to
    explicitly opt out (no effect either way).
    """
    directory = Path(directory)
    parent_files = sorted(directory.glob(parent_glob))

    # Collect subagent files correlated to each parent by stem (session ID).
    subagent_files = []
    for pf in parent_files:
        subagent_files += sorted(directory.glob(f"{pf.stem}/subagents/*.jsonl"))

    files = parent_files + subagent_files

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
        t = totals[tier]
        p = priced[tier]
        lines.append(
            f"| {tier.capitalize()} | {t.get('turns',0):,} "
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

    totals = aggregate_directory(args.directory)
    priced = price_totals(totals)

    if args.markdown:
        print(render_markdown(totals, priced))
        return

    # Plain-text breakdown
    print(f"Audit of {args.directory}\n")
    grand_full = grand_unc = 0.0
    for tier in ("opus", "sonnet", "haiku"):
        if tier not in totals:
            continue
        t = totals[tier]
        p = priced[tier]
        print(f"  {tier:<7} turns={t.get('turns',0):>6,d}  "
              f"uncached=${p['uncached']:>9,.2f}  full=${p['full']:>9,.2f}")
        grand_full += p["full"]
        grand_unc  += p["uncached"]
    print(f"  {'TOTAL':<7}                 "
          f"uncached=${grand_unc:>9,.2f}  full=${grand_full:>9,.2f}")


if __name__ == "__main__":
    main()
