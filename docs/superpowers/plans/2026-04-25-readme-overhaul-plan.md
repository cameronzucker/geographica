# README overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Project policy:** worktrees BANNED (per CLAUDE.md). Execute in main checkout on `dev` branch. Each task commits immediately. Destructive git commands BANNED — see CLAUDE.md "Git workflow — destructive commands are BANNED" section.
>
> **Moniker:** every commit gets `Agent: <moniker>` trailer. Controller's moniker is `tinaja`; subagents pick their own (avoid collisions: `git log --grep="^Agent: " --format="%(trailers:key=Agent,valueonly)" | sort -u` before picking).
>
> **Voice rule (load-bearing across all 5 docs):** declarative third-person, no first-person. See `feedback_writing_voice_no_first_person.md`. If a sentence resists declarative framing, restructure rather than concede.

**Goal:** Replace the current 838-line monolithic `README.md` with a 5-document set (README + SETUP + MANUAL_SETUP + PROCESS + COST_METHODOLOGY) plus supporting assets (audit script, screenshots, custom OG image, Mermaid architecture diagram, custom badges) suitable for showing the project to senior technical and executive audiences.

**Architecture:** Progressive disclosure across 5 docs. README is ~210 lines, organized so each audience tier (exec / peer / leadership / user) reads top-to-bottom and bails when satisfied. Sibling docs are first-class linkable artifacts. Screenshot capture uses a Mixed strategy: Playwright (already installed in `dev/harness/`) for desktop shots, manual capture for GPS-pinned hero + in-vehicle mobile shot. Image post-processing via Pillow.

**Tech Stack:** Markdown (GitHub-flavored), Mermaid (native GH rendering since 2022), Python 3.11+ for the audit + capture scripts, Playwright (already installed), Pillow for PNG post-processing, pytest for the audit-script tests.

**Spec:** [docs/superpowers/specs/2026-04-25-readme-overhaul-design.md](../specs/2026-04-25-readme-overhaul-design.md) (committed `b52e0d9`).

---

## File structure

**Created:**

| File | Responsibility |
|---|---|
| `scripts/audit_inference_cost.py` | Productionized cost audit. Reads `~/.claude/projects/<project>/`, sums tokens by tier, prices at published rates, outputs markdown table. |
| `tests/test_audit_inference_cost.py` | pytest suite — fixture-based unit tests for token aggregation and pricing math. |
| `tests/fixtures/audit_inference_cost/parent_opus_only.jsonl` | Single-session fixture: one Opus turn with known token counts. |
| `tests/fixtures/audit_inference_cost/parent_with_subagent_dir.jsonl` | Parent transcript that spawned subagents (used with sibling subagent dir). |
| `tests/fixtures/audit_inference_cost/<sessid>/subagents/sub1.jsonl` | Subagent transcript fixture with mixed-tier turns. |
| `scripts/capture_readme_screenshots.py` | Playwright capture script for the 4 desktop shots (3D terrain, voice search, public lands, admin pipeline) + 3 gallery shots (setup wizard, KMZ, imagery before/after). |
| `scripts/postprocess_screenshots.py` | Pillow post-processing — applies subtle border + drop shadow to desktop PNGs; composites mobile PNGs into a phone frame. |
| `scripts/audit_doc_links.sh` | Walks every relative link in `README.md` + `docs/*.md` and verifies they resolve. |
| `docs/SETUP.md` | Wizard happy path (~150 lines, audience D users). |
| `docs/MANUAL_SETUP.md` | Sections 1-12 of the current `README.md` "Manual setup" + migrated sections (Stack management, Troubleshooting, Customizing coverage, Ports). ~500 lines. |
| `docs/PROCESS.md` | Meta-story as first-class linkable artifact. ~250 lines. |
| `docs/COST_METHODOLOGY.md` | Cost audit + reproduction. ~120 lines. |
| `docs/og-image.png` | 1200×630 social-share image — composited from a hero screenshot + wordmark. |
| `docs/screenshots/hero-everything.png` | Map + NAIP imagery + GPS pin + active turn-by-turn route + maneuver banner. **Manual capture (Cameron).** |
| `docs/screenshots/3d-terrain.png` | 3D terrain w/ hillshade + exaggeration slider. Playwright capture. |
| `docs/screenshots/voice-search.png` | Voice search active + result list + numbered map pins. Playwright capture. |
| `docs/screenshots/public-lands.png` | Public lands layer w/ legend. Playwright capture. |
| `docs/screenshots/admin-pipeline.png` | Admin → Pipelines tab w/ minimap + active progress. Playwright capture. |
| `docs/screenshots/mobile-nav.png` | Phone screenshot, in-vehicle, nav running. **Manual capture (Cameron).** |
| `docs/screenshots/gallery/setup-wizard.png` | Setup wizard step 3 — clean dark mode, progress dots. Playwright. |
| `docs/screenshots/gallery/kmz-overlay.png` | Drag-drop KMZ overlay + layer panel + custom icons. Playwright. |
| `docs/screenshots/gallery/imagery-before-after.png` | Side-by-side: basemap only vs. NAIP overlay. Playwright (or composited from two Playwright shots). |

**Modified:**

| File | Lines | Change |
|---|---|---|
| `README.md` | 1-838 | Full rewrite. Final length ~210 lines, 11 sections per spec §5. |
| `dev/implementation-log.md` | top | Append entry for this overhaul (per CLAUDE.md commit discipline). |

**Untouched** (explicitly out of scope per spec §8): `CHANGELOG.md`, `CONTRIBUTING.md`, `VERSIONING.md`, `UPGRADING.md`, `LICENSE`, `AGENTS.md`, `CLAUDE.md`, anything in `dev/` except `implementation-log.md`, anything in `frontend/`, `services/`, `scripts/` other than the three new scripts above.

---

## Sequencing

Per spec §11: content-first, assets-second.

| Phase | Tasks | Goal | Parallelizable |
|---|---|---|---|
| 0 | T0.1–T0.3 | Audit script foundation. Unblocks COST_METHODOLOGY.md. | No (TDD chain) |
| 1 | T1.1–T1.5 | New README skeleton + extraction of MANUAL_SETUP.md + new SETUP.md | T1.4 parallel with T1.2/T1.3 |
| 2 | T2.1 | COST_METHODOLOGY.md from audit-script output | No |
| 3 | T3.1–T3.7 | PROCESS.md, written section-by-section | Yes — sections can be parallel |
| 4 | T4.1–T4.4 | README content (features, architecture diagram, header/badges, callout) | T4.1–T4.3 parallel |
| 5 | T5.1–T5.10 | Screenshot capture + post-processing + embedding | T5.2–T5.6 parallel; T5.7 user-driven |
| 6 | T6.1–T6.4 | OG image + cross-link audit + Mermaid render verification | Mostly sequential |
| 7 | T7.1–T7.2 | User end-to-end review + impl-log entry + final commit | Sequential |

**Acceptance gate after each phase:** plan checkpoint commit summarizing what landed. Subagent-driven-development should pause at phase boundaries for human or controller review.

---

# Phase 0 — Cost audit foundation

Goal: a productionized, tested audit script that reproduces the brainstorm's $2,489 / $21,858 numbers from this project's transcripts. Required by Phase 2 (COST_METHODOLOGY.md).

---

### Task 0.1: Write audit script test fixtures

**Files:**
- Create: `tests/fixtures/audit_inference_cost/parent_opus_only.jsonl`
- Create: `tests/fixtures/audit_inference_cost/parent_with_subagent_ref.jsonl`
- Create: `tests/fixtures/audit_inference_cost/abc123/subagents/sub_sonnet.jsonl`
- Create: `tests/fixtures/audit_inference_cost/empty.jsonl`

- [ ] **Step 1: Create the fixtures directory tree**

```bash
mkdir -p tests/fixtures/audit_inference_cost/abc123/subagents
```

- [ ] **Step 2: Write `parent_opus_only.jsonl`** (single Opus turn, deterministic token counts)

```jsonl
{"type":"user","message":{"role":"user","content":"hi"}}
{"type":"assistant","message":{"role":"assistant","model":"claude-opus-4-7[1m]","content":[{"type":"text","text":"hello"}],"usage":{"input_tokens":10,"cache_creation_input_tokens":1000,"cache_read_input_tokens":5000,"cache_creation":{"ephemeral_5m_input_tokens":200,"ephemeral_1h_input_tokens":800},"output_tokens":50,"service_tier":"standard"}}}
```

Expected costs at Opus rates ($15/M input, $75/M output, cache write 5m=$18.75/M, cache write 1h=$30/M, cache read=$1.50/M):
- Input: 10 / 1e6 × 15 = $0.00015
- Cache 5m: 200 / 1e6 × 18.75 = $0.00375
- Cache 1h: 800 / 1e6 × 30 = $0.024
- Cache read: 5000 / 1e6 × 1.5 = $0.0075
- Output: 50 / 1e6 × 75 = $0.00375
- **Total: ~$0.039**

- [ ] **Step 3: Write `parent_with_subagent_ref.jsonl`** (one parent Opus turn that invoked a subagent)

```jsonl
{"type":"user","message":{"role":"user","content":"do the thing"}}
{"type":"assistant","message":{"role":"assistant","model":"claude-opus-4-7[1m]","content":[{"type":"tool_use","name":"Agent","input":{}}],"usage":{"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":2000,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0},"output_tokens":100,"service_tier":"standard"}}}
```

- [ ] **Step 4: Write `abc123/subagents/sub_sonnet.jsonl`** (subagent transcript with Sonnet + Haiku turns)

```jsonl
{"type":"user","message":{"role":"user","content":"go"}}
{"type":"assistant","message":{"role":"assistant","model":"claude-sonnet-4-6","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":20,"cache_creation_input_tokens":0,"cache_read_input_tokens":3000,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0},"output_tokens":80,"service_tier":"standard"}}}
{"type":"assistant","message":{"role":"assistant","model":"claude-haiku-4-5-20251001","content":[{"type":"text","text":"done"}],"usage":{"input_tokens":5,"cache_creation_input_tokens":0,"cache_read_input_tokens":1000,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":0},"output_tokens":30,"service_tier":"standard"}}}
```

- [ ] **Step 5: Write `empty.jsonl`** (defensive — script must not crash on empty file)

```
```

(Yes, empty. Just `touch tests/fixtures/audit_inference_cost/empty.jsonl`.)

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/audit_inference_cost/
git commit -m "$(cat <<'EOF'
test(audit-cost): fixture transcripts for inference-cost audit

Three synthetic transcript fixtures covering: pure-Opus parent,
parent-with-subagent-spawn, mixed-tier subagent (Sonnet+Haiku), and
empty file. All token counts deterministic so pricing math can be
unit-tested.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.2: Write audit script with TDD

**Files:**
- Create: `scripts/audit_inference_cost.py`
- Create: `tests/test_audit_inference_cost.py`

- [ ] **Step 1: Write the failing test for token aggregation**

```python
# tests/test_audit_inference_cost.py
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from audit_inference_cost import aggregate_directory, price_totals, PRICING

FIXTURES = Path(__file__).parent / "fixtures" / "audit_inference_cost"


def test_aggregate_single_opus_turn():
    totals = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl")
    assert totals["opus"]["input"] == 10
    assert totals["opus"]["cache_w_5m"] == 200
    assert totals["opus"]["cache_w_1h"] == 800
    assert totals["opus"]["cache_r"] == 5000
    assert totals["opus"]["output"] == 50
    assert totals["opus"]["turns"] == 1
    assert "sonnet" not in totals
    assert "haiku" not in totals


def test_empty_file_does_not_crash():
    totals = aggregate_directory(FIXTURES, parent_glob="empty.jsonl")
    # Empty file → no turns recorded but no exception
    assert totals == {} or all(t.get("turns", 0) == 0 for t in totals.values())


def test_subagent_transcripts_are_picked_up():
    """Subagent dir lives at <project>/<sessid>/subagents/*.jsonl."""
    totals = aggregate_directory(FIXTURES, parent_glob="parent_with_subagent_ref.jsonl")
    # Parent contributed Opus
    assert totals["opus"]["turns"] >= 1
    # Subagent dir abc123/ contributed Sonnet + Haiku
    assert totals["sonnet"]["turns"] == 1
    assert totals["haiku"]["turns"] == 1


def test_price_totals_opus_known_values():
    totals = aggregate_directory(FIXTURES, parent_glob="parent_opus_only.jsonl")
    priced = price_totals(totals)
    # Match the brainstorm-verified pricing at $15/$75 for Opus, with cache 5m=1.25x, 1h=2x, read=0.1x
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/administrator/Code/geographica && python -m pytest tests/test_audit_inference_cost.py -v
```

Expected: 4 errors with `ModuleNotFoundError: No module named 'audit_inference_cost'` (or similar — script doesn't exist yet).

- [ ] **Step 3: Write the audit script (minimal, makes tests pass)**

```python
# scripts/audit_inference_cost.py
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
import glob
import json
import os
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
    """Sum token counts across parent and subagent transcripts in a directory."""
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/administrator/Code/geographica && python -m pytest tests/test_audit_inference_cost.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Run the script against this project for sanity check**

```bash
cd /home/administrator/Code/geographica && python3 scripts/audit_inference_cost.py ~/.claude/projects/-home-administrator-Code-geographica/
```

Expected: numbers within ±1% of the brainstorm-verified $2,489 uncached / $21,858 full.

- [ ] **Step 6: Commit**

```bash
git add scripts/audit_inference_cost.py tests/test_audit_inference_cost.py
git commit -m "$(cat <<'EOF'
feat(audit): inference-cost audit script for Claude Code transcripts

Reads ~/.claude/projects/<slug>/ (parents + subagents), sums tokens by
tier, prices at Anthropic's published rates. Reports both "uncached"
(input + output, ccusage convention) and "full" (with cache writes +
reads at 1.25x/2x/0.1x input). Markdown output mode for embedding in
COST_METHODOLOGY.md.

Tested with 4 fixture transcripts; reproduces $2,489 / $21,858 against
this project's on-disk transcripts.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 0.3: Generate the canonical cost-table snippet

**Files:**
- Create: `dev/notes/cost-audit-snapshot-2026-04-25.md` (working file, gitignored — for use in COST_METHODOLOGY.md)

- [ ] **Step 1: Run the audit and capture output**

```bash
cd /home/administrator/Code/geographica
python3 scripts/audit_inference_cost.py ~/.claude/projects/-home-administrator-Code-geographica/ --markdown > dev/notes/cost-audit-snapshot-2026-04-25.md
cat dev/notes/cost-audit-snapshot-2026-04-25.md
```

Expected: a markdown table with three rows (Opus, Sonnet, Haiku) and a totals row, with grand totals matching brainstorm.

- [ ] **Step 2: Manual verification**

Open the file and confirm:
- Opus turns ≈ 47,689 (range 47,000–48,000)
- Sonnet turns ≈ 16,878 (range 16,000–17,500)
- Haiku turns ≈ 18,772 (range 18,000–19,500)
- Uncached total ≈ $2,489 (range $2,400–$2,600)
- Full total ≈ $21,858 (range $21,000–$23,000)

**Why ranges:** the project is still active; numbers will drift slightly between brainstorm and now.

- [ ] **Step 3: No commit needed** — file is gitignored. Hold for use in Task 2.1.

---

# Phase 1 — Doc skeleton + extraction

Goal: the file structure exists and is navigable end-to-end. Content can be stubbed; what matters is that links work and the doc set is in place.

---

### Task 1.1: New README skeleton (sections only, content stubbed)

**Files:**
- Modify: `README.md` (full rewrite — but Phase 4 fills in content)

- [ ] **Step 1: Save the current README for migration reference**

```bash
cp /home/administrator/Code/geographica/README.md /home/administrator/Code/geographica/dev/notes/README-pre-overhaul.md
```

(`dev/notes/` is gitignored — this is a working artifact, not a checked-in backup.)

- [ ] **Step 2: Replace `README.md` with the skeleton**

The skeleton contains all 11 sections from spec §5, with prose stubbed where content lands later. Headings and structural elements are final; prose blocks marked `<!-- TODO: Phase N Task X.Y -->` for traceability.

```markdown
<!-- HEADER -->
<img src="docs/geographica_favicon.png" width="80" height="80" align="left" alt="Geographica favicon" />

# Geographica

<!-- TODO: Phase 4 Task 4.3 — tagline + badge row -->

<br clear="left" />

<!-- ONE-PARAGRAPH ELABORATION -->
<!-- TODO: Phase 4 Task 4.4 — what + why in two sentences -->

<!-- HERO SCREENSHOT -->
<!-- TODO: Phase 5 Task 5.10 — hero image embed -->

<!-- HOW IT WAS BUILT CALLOUT -->
<!-- TODO: Phase 4 Task 4.4 — meta-callout with cost prose + 2 trailing links -->

## Features

<!-- TODO: Phase 4 Task 4.1 — 4 thematic groups, each with inline screenshot -->

## Architecture

<!-- TODO: Phase 4 Task 4.2 — Mermaid flowchart -->

## Hardware requirements

<!-- TODO: Phase 4 Task 4.4 — min/recommended + storage budget tables (lift from old README §"Hardware requirements", lines 42-77) -->

## Get started

<!-- TODO: Phase 4 Task 4.4 — 4-line wizard quick-start + links to SETUP / MANUAL_SETUP -->

## Project layout

<!-- TODO: Phase 4 Task 4.4 — compact ASCII tree -->

## Further reading

- [docs/SETUP.md](docs/SETUP.md) — guided wizard install (5 minutes)
- [docs/MANUAL_SETUP.md](docs/MANUAL_SETUP.md) — manual install + advanced configuration
- [docs/PROCESS.md](docs/PROCESS.md) — how this was built with an AI agent team
- [docs/COST_METHODOLOGY.md](docs/COST_METHODOLOGY.md) — cost audit + reproduction
- [CHANGELOG.md](CHANGELOG.md) — release history
- [CONTRIBUTING.md](CONTRIBUTING.md) — commit conventions and PR flow
- [VERSIONING.md](VERSIONING.md) — versioning policy and hotfix recipe
- [UPGRADING.md](UPGRADING.md) — version-to-version migration notes

## License

MIT — see [LICENSE](LICENSE).
```

- [ ] **Step 3: Verify the skeleton renders without obvious breakage**

```bash
cd /home/administrator/Code/geographica
wc -l README.md
grep -c "TODO: Phase" README.md
```

Expected: `README.md` is ~50-70 lines (skeleton only); 7-8 `TODO: Phase` markers (each marker is a tracked unblocking gate).

- [ ] **Step 4: Commit the skeleton**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): skeleton for multi-doc overhaul (Phase 1)

Replaces the 838-line monolith with the section structure from spec §5.
Prose blocks stubbed with TODO markers tagged to the Phase + Task that
will fill them in. The "Further reading" section is fully populated
(links work; sibling docs added in subsequent Phase 1 tasks).

Per spec docs/superpowers/specs/2026-04-25-readme-overhaul-design.md
(commit b52e0d9). Implementation plan at
docs/superpowers/plans/2026-04-25-readme-overhaul-plan.md.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.2: Extract MANUAL_SETUP.md from the old README

**Files:**
- Create: `docs/MANUAL_SETUP.md`
- Reference (read-only): `dev/notes/README-pre-overhaul.md` (saved in Task 1.1)

- [ ] **Step 1: Create the new file with header**

```markdown
# Manual setup

> **Most users want [docs/SETUP.md](SETUP.md) instead** — it covers the wizard-driven happy path that takes ~5 minutes.
>
> This document is for advanced users, recovery scenarios, and AI agents that need a fully-explicit step-by-step reference. Every step the wizard takes for you is documented here so it can be reproduced or audited by hand.

## Prerequisites

<!-- migrated content lands here -->
```

- [ ] **Step 2: Migrate sections from `dev/notes/README-pre-overhaul.md`**

From the old README, lift sections **verbatim** (no rewriting — that's a separate scope per spec §9.3):
- §"Manual setup" header + intro paragraph (lines 131-138)
- §"Prerequisites" (lines 139-186)
- §"1. Clone the repo" (lines 187-193)
- §"2. Create the data directory" (lines 194-204)
- §"3. Configure environment" (lines 205-228)
- §"4. Download OSM data" (lines 229-256)
- §"5. Generate vector basemap tiles" (lines 257-277)
- §"6. Download elevation tiles" (lines 278-294)
- §"7. Build the POI search index" (lines 295-307)
- §"7b. Extract OSM amenities and public land boundaries" (lines 308-320)
- §"7c. Build public lands vector tiles (optional)" (lines 321-347)
- §"8. Set up TileServer GL styles and fonts" (lines 348-376)
- §"9. Frontend vendor libraries" (lines 377-392)
- §"10. Configure GPS (optional)" (lines 393-430)
- §"11. Launch the stack" (lines 431-466)
- §"12. Verify the deployment" (lines 467-494)

(Line ranges are approximate — they reference the old `README.md`. After lift, all these become `## ` and `### ` headings inside `MANUAL_SETUP.md`. Demote one level if needed so MANUAL_SETUP.md only has one `# ` at top.)

- [ ] **Step 3: Verify no `<!-- TODO -->` markers were copied across**

```bash
grep -n "TODO" /home/administrator/Code/geographica/docs/MANUAL_SETUP.md
```

Expected: no output (the source had none in this section).

- [ ] **Step 4: Verify line count is roughly in budget**

```bash
wc -l /home/administrator/Code/geographica/docs/MANUAL_SETUP.md
```

Expected: ~370-420 lines (the migrated 12 sections, before Task 1.3 adds the rest).

- [ ] **Step 5: Commit**

```bash
git add docs/MANUAL_SETUP.md
git commit -m "$(cat <<'EOF'
docs(manual-setup): extract sections 1-12 from pre-overhaul README

Lift §"Manual setup" §1-12 verbatim from the old README into a new
sibling doc. Per spec §6.2, no rewriting — that's a separate scope.
Header notes that most users should use SETUP.md (wizard) instead.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.3: Migrate operational sections to MANUAL_SETUP.md

**Files:**
- Modify: `docs/MANUAL_SETUP.md`

- [ ] **Step 1: Append the four operational sections from the old README**

Lift verbatim from `dev/notes/README-pre-overhaul.md`:
- §"Stack management" (lines 495-510)
- §"Config panel" (lines 511-545)
- §"HTTPS via Tailscale" (lines 546-577)
- §"Companion data utility" (lines 578-595)
- §"Customizing coverage area" (lines 596-615)
- §"Ports" (lines 616-635)
- §"Troubleshooting" (lines 636-722)

Note: §"Companion data utility" is a 2-section consideration — half belongs in MANUAL_SETUP.md (the operational "how to use it" half) and half belongs in PROCESS.md (the meta-story about why it was built). For this task, lift only the operational portion into MANUAL_SETUP.md; PROCESS.md picks it up in Task 3.6.

- [ ] **Step 2: Sanity-check the section ordering**

After this task, MANUAL_SETUP.md sections in order should read:
1. Prerequisites
2. Clone the repo
3. Create the data directory
4. Configure environment
5. Download OSM data
6. Generate vector basemap tiles
7. Download elevation tiles
8. Build the POI search index
9. Extract OSM amenities and public land boundaries
10. Build public lands vector tiles (optional)
11. Set up TileServer GL styles and fonts
12. Frontend vendor libraries
13. Configure GPS (optional)
14. Launch the stack
15. Verify the deployment
16. Stack management
17. Config panel
18. HTTPS via Tailscale
19. Companion data utility (operational portion)
20. Customizing coverage area
21. Ports
22. Troubleshooting

- [ ] **Step 3: Verify line count**

```bash
wc -l /home/administrator/Code/geographica/docs/MANUAL_SETUP.md
```

Expected: ~480-520 lines (close to the spec's ~500 estimate).

- [ ] **Step 4: Commit**

```bash
git add docs/MANUAL_SETUP.md
git commit -m "$(cat <<'EOF'
docs(manual-setup): migrate stack-mgmt + Tailscale + ops sections

Lift Stack management, Config panel, HTTPS via Tailscale, Companion
utility (operational portion only), Customizing coverage, Ports, and
Troubleshooting from the old README. Verbatim — no rewriting per
spec §9.3.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.4: Write SETUP.md (wizard happy path)

**Files:**
- Create: `docs/SETUP.md`

This task can run in parallel with T1.2/T1.3 — independent file.

- [ ] **Step 1: Draft the document**

```markdown
# Setup

The fastest way to get Geographica running on a fresh Raspberry Pi 5. This document walks the wizard-driven install path that handles credentials, data acquisition, TLS, and the stack itself end-to-end.

For the manual install (advanced users, recovery scenarios, AI agents needing a step-by-step reference), see [MANUAL_SETUP.md](MANUAL_SETUP.md).

## Before you start

You'll need:

| Component | Notes |
|---|---|
| Raspberry Pi 5 (16 GB recommended) | 8 GB works for single-state coverage; 16 GB recommended for multi-state |
| Storage | 256 GB SSD minimum (single-state); 1 TB SSD recommended for multi-state coverage |
| Network | Internet connection during initial data acquisition only — Geographica runs offline after setup |
| Time | ~30 minutes of attended time + several hours of background data download |

For credentials needed during setup (USGS M2M API key, etc.), see [Step 4 — Credentials](#step-4-credentials).

## Step 1 — Bootstrap

Install system prerequisites (apt packages, docker, the docker group). Requires sudo.

\`\`\`bash
git clone https://github.com/cameronzucker/geographica.git
cd geographica
sudo ./bootstrap.sh
\`\`\`

After this completes, **log out and back in** so the docker group membership takes effect. (If you skip this, every later step that runs docker will fail with a permission error.)

## Step 2 — Launch the wizard

\`\`\`bash
./setup.sh
\`\`\`

This creates a Python virtual environment and starts the wizard server at http://localhost:8099. Open that URL in any browser on the Pi (or via SSH port-forward from your laptop).

<!-- TODO: Phase 5 Task 5.6 — gallery wizard screenshot -->

## Step 3 — Walk the wizard

The wizard has 5 steps:

1. **Welcome + system check** — confirms the bootstrap step ran successfully, checks disk space and memory.
2. **Coverage area** — choose your region by state list or by drawing a bounding box on a map. Determines how much data gets downloaded.
3. **Data sources** — pick which imagery and elevation sources to use. The wizard explains the tradeoffs (free vs. requires-account; resolution; coverage area). Defaults are sensible.
4. **Credentials** — paste any required API keys. They're stored in the system keychain (GNOME Keyring), never in plaintext files. See [Step 4](#step-4-credentials) below if you don't have an account yet.
5. **Confirm + launch** — reviews choices, kicks off the data pipeline, brings up the docker stack.

## Step 4 — Credentials

Some imagery sources require an account. The wizard tells you which sources need credentials and links to the signup page for each. For the cleanest experience, sign up for these **before** starting the wizard:

- **USGS ERS account** (for the M2M API mode — z19 NAIP at the highest available resolution): free at https://ers.cr.usgs.gov/register
- **NOAA Digital Coast** (for z17 NAIP at moderate resolution, no throttling): no account required, but allow ~6-12 hours for a state-sized download

If you skip credential-gated sources, the wizard falls back to USGS Direct (z0-z14, no account) and NOAA NAIP (z17, no account) — these alone produce a fully functional stack.

## Step 5 — Verify

After the wizard completes, the stack should be running on http://localhost:8093.

\`\`\`bash
docker compose ps
\`\`\`

Expected: 7 services in `Up (healthy)` state — `tileserver`, `valhalla`, `nominatim`, `gps`, `search`, `stt`, `frontend`.

\`\`\`bash
curl -s http://localhost:8093/health
\`\`\`

Expected: `{"status":"ok"}`.

Open http://localhost:8093 in your browser. You should see the map centered on your coverage area, with basemap tiles loading.

## Common issues

**Wizard says "docker not in PATH" or "permission denied"** — you didn't log out and back in after `bootstrap.sh`. Log out, log back in, retry `./setup.sh`.

**Wizard hangs at "downloading vector tiles"** — Planetiler is CPU-intensive and slow on Pi 5; expect 30-60 minutes for a multi-state region. The progress bar updates infrequently; check `docker compose logs -f tileserver` for activity.

**"No available imagery in your bounding box"** — your region may not have NOAA NAIP coverage. Switch to USGS Direct (always available, lower resolution) in the wizard's data-sources step, or try a different region.

**Stack starts but the map is blank** — check `docker compose logs frontend` and `docker compose logs tileserver`. Most blank-map issues are missing tile data; rerun the wizard's data-acquisition step or use the admin panel at http://localhost:8097 to inspect inventory.

For more, see the [Troubleshooting section in MANUAL_SETUP.md](MANUAL_SETUP.md#troubleshooting).

## When you outgrow this

The wizard handles ~95% of cases. If you need any of the following, you'll want [MANUAL_SETUP.md](MANUAL_SETUP.md):

- BYO GeoTIFF imagery (importing your own pre-acquired data)
- Custom coverage area beyond what the wizard's bounding-box selector can express
- Reproducing the install from scratch on a different Pi (the wizard's state lives in keyring + config files; manual setup is more portable)
- Recovery from a partial install where the wizard can't make forward progress
- Running Geographica without docker (not officially supported, but documented for AI agents that need step-by-step grounding)
```

- [ ] **Step 2: Verify line count is in spec budget**

```bash
wc -l /home/administrator/Code/geographica/docs/SETUP.md
```

Expected: ~140-170 lines.

- [ ] **Step 3: Voice check**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/SETUP.md
```

Expected: no output. (Per voice rule. If matches found, restructure those sentences.)

- [ ] **Step 4: Commit**

```bash
git add docs/SETUP.md
git commit -m "$(cat <<'EOF'
docs(setup): wizard happy-path quick-start

Per spec §6.1 — 6-section wizard walkthrough sized for ~30-minute
time-to-stack on a fresh Pi 5. Surfaces the credential decisions
upfront and points at MANUAL_SETUP.md for advanced cases. Voice rule
holds (no first-person).

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 1.5: Verify Phase 1 cross-links resolve

**Files:**
- Reference (no edits): `README.md`, `docs/SETUP.md`, `docs/MANUAL_SETUP.md`

- [ ] **Step 1: Check that every relative link from the new docs resolves**

```bash
cd /home/administrator/Code/geographica
# Every relative .md link in our 3 new/changed files
for src in README.md docs/SETUP.md docs/MANUAL_SETUP.md; do
  grep -oE "\\]\\([a-zA-Z0-9_./-]+\\.md(#[a-zA-Z0-9-]+)?\\)" "$src" \
    | sed -E 's/\\]\\(([^)]+)\\)/\\1/' \
    | while read link; do
      target="${link%%#*}"
      [ -z "$target" ] && continue
      # Resolve relative to source file's dir
      dir=$(dirname "$src")
      [ -e "$dir/$target" ] || echo "BROKEN: $src -> $link"
    done
done
```

Expected: no `BROKEN:` lines.

- [ ] **Step 2: Document the verification in the impl log (defer to Task 7.2)** — no commit here, just observed.

---

# Phase 2 — COST_METHODOLOGY.md

Goal: ship the full cost-audit disclosure that the README's callout links to.

---

### Task 2.1: Write COST_METHODOLOGY.md

**Files:**
- Create: `docs/COST_METHODOLOGY.md`
- Reference: `dev/notes/cost-audit-snapshot-2026-04-25.md` (from Task 0.3)

- [ ] **Step 1: Draft the document**

```markdown
# Cost methodology

Geographica was built with the help of a team of Claude agents over 19 days. This document shows where every cost number in the README comes from, discloses the full audit, and ships the script that produced it so anyone can reproduce or challenge the methodology.

## Headline number — ~$2,500

The README quotes "**~$2,500 of API-equivalent model output**" in its "How it was built" callout. This is the cost of the model's actual generation work, computed as:

\`\`\`
(uncached input tokens × $15/M) + (output tokens × $75/M)   # for Opus
(uncached input tokens × $3/M)  + (output tokens × $15/M)   # for Sonnet
(uncached input tokens × $1/M)  + (output tokens × $5/M)    # for Haiku
\`\`\`

This matches what `ccusage` and similar third-party tools report. It represents what would have been billed if these prompts were submitted to the Anthropic API directly, with no subscription, and only the input + output were charged.

## Full list-price number — ~$22,000

The full Anthropic list price, including cache reads and writes, is **~$21,858** for this project. Cache reads dominate at ~$12,100, because Claude Code re-loads the system prompt, tool definitions, hooks, and files-in-scope on every conversational turn (~336K tokens per turn × 47K turns).

Cache reads are priced at 10% of input ($1.50/M for Opus). Cache writes are priced at 125% of input for the 5-minute tier ($18.75/M) and 200% for the 1-hour tier ($30/M). The math:

| Component | Tokens | Rate | Cost |
|---|---:|---:|---:|
| Input (uncached) | 0.26 M | $15/M | $3.94 |
| Cache write — 5 min | 4.69 M | $18.75/M | $87.91 |
| Cache write — 1 hour | 106.06 M | $30.00/M | $3,181.85 |
| Cache read | 8,081.54 M | $1.50/M | $12,122.31 |
| Output | 25.11 M | $75/M | $1,883.24 |
| **Total (Opus only)** | | | **$17,279.25** |
| Sonnet (subagents) | | | $364.75 |
| Haiku (subagents) | | | $148.93 |
| **Grand total** | | | **$17,792.93** |

(Numbers above are from the brainstorm-time snapshot. The current snapshot is below; the project is still active so values drift slightly.)

### Current snapshot

[ paste output of `python3 scripts/audit_inference_cost.py ~/.claude/projects/-home-administrator-Code-geographica/ --markdown` here — see Task 0.3 ]

## What was actually paid

| Item | Cost | Notes |
|---|---|---|
| Claude Max subscription | ~$200/month | One month covered the entire project |
| Hardware | (See README hardware section) | Pi 5 + SSD; cost varies and ages quickly |
| Other inference | $0 | No API tokens beyond the subscription |

Total out-of-pocket: **~$200/month** for the duration of active development, plus a Pi-class single-board computer.

## Why two numbers, not one

The $2,500 and $22,000 numbers describe the same project, but answer different questions:

- **$2,500** is the honest measure of *model work* — how many tokens the model actually generated, and how much novel input it had to read.
- **$22,000** is the honest list price *if cache reads were billed* — what Anthropic would charge for the full workload at API rates with no subscription.

Cache reads are a property of the agent harness (Claude Code), not the work itself. A different harness with smarter context handling could substantially reduce that number without changing what was built. Treating cache reads as overhead (the way `ccusage` does) gives a number that scales with work output rather than session length, which is the more meaningful comparison across projects.

The README leads with $2,500 because that's the number a peer or an executive can reason about. This page shows the $22,000 because hiding it would be dishonest.

## Reproduction

The script that produced these numbers is at [`scripts/audit_inference_cost.py`](../scripts/audit_inference_cost.py). Run it against any Claude Code project transcript directory:

\`\`\`bash
python3 scripts/audit_inference_cost.py ~/.claude/projects/<project-slug>/ --markdown
\`\`\`

Output is a markdown table identical in structure to the "Current snapshot" section above. The script is unit-tested with synthetic transcript fixtures at `tests/fixtures/audit_inference_cost/`; see `tests/test_audit_inference_cost.py` for the math.

Pricing constants in the script reflect Anthropic's published rates as of 2026-04. If rates change, update the `PRICING` dict at the top of the script and re-run.
```

- [ ] **Step 2: Replace the "Current snapshot" placeholder with real output**

```bash
cd /home/administrator/Code/geographica
SNAPSHOT=$(python3 scripts/audit_inference_cost.py ~/.claude/projects/-home-administrator-Code-geographica/ --markdown)
# Use a Python one-liner or Edit tool to substitute into docs/COST_METHODOLOGY.md
```

- [ ] **Step 3: Voice check**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/COST_METHODOLOGY.md
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add docs/COST_METHODOLOGY.md
git commit -m "$(cat <<'EOF'
docs(cost): COST_METHODOLOGY.md — full audit + reproduction

Per spec §6.4. Discloses both the $2.5K headline (uncached I/O,
matches ccusage) and the $21.8K full list price (with cache writes
+ reads at 1.25x/2x/0.1x input). Explains why two numbers describe
the same project. Embeds current snapshot from
scripts/audit_inference_cost.py and points the reader at the script
for self-reproduction.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 3 — PROCESS.md

Goal: the meta-story as a first-class linkable artifact. Most novel document in the set; most at risk of voice-rule friction (per spec §9.5). Each section gets its own task to keep prose tight and reviewable.

---

### Task 3.1: PROCESS.md §1 — What was built, in numbers

**Files:**
- Create: `docs/PROCESS.md`

- [ ] **Step 1: Compute current numbers**

```bash
cd /home/administrator/Code/geographica
echo "Days: $(git log --reverse --format=%ad --date=short | head -1) → $(git log -1 --format=%ad --date=short)"
echo "Commits: $(git log --format=%H | wc -l)"
echo "Agents: $(git log --format='%(trailers:key=Agent,valueonly)' | grep -v '^$' | grep -v -- '-impl-' | sort -u | wc -l)"
echo "Specs: $(ls docs/superpowers/specs/ | wc -l)"
echo "Plans: $(ls docs/superpowers/plans/ | wc -l)"
echo "Test files: $(find . -name 'test_*.py' -not -path '*/node_modules/*' -not -path '*/.venv/*' -not -path '*/site-packages/*' | wc -l)"
```

Hold these numbers for the prose.

- [ ] **Step 2: Draft §1**

```markdown
# How Geographica was built

Geographica is a working example of AI-orchestrated software development: a single human engineer working with a team of Claude agents, under structured workflows, on a constrained budget. This document is the meta-story behind the artifact — what was built, how, and what the methodology says about transferring these techniques to higher-stakes work.

## 1. What was built, in numbers

| | |
|---|---|
| Calendar duration | 19 days (2026-04-06 → 2026-04-25) |
| Commits | [N from Step 1] |
| Named agents | [N from Step 1] (excluding subagent-instance suffixes) |
| Spec documents | [N from Step 1] |
| Implementation plans | [N from Step 1] |
| Test files | [N from Step 1] |
| Persistent services | 7 (TileServer GL, Valhalla, Nominatim, Search, STT, GPS, Frontend) plus an on-demand pipeline container |
| Inference cost | ~$2,500 model output at API rates ([cost methodology](COST_METHODOLOGY.md)) |
| Hardware target | Raspberry Pi 5 |

Geographica is feature-complete for offline-first GIS use on AREDN mesh networks: vector basemaps, aerial imagery acquisition (5 modes), 3D terrain, turn-by-turn navigation with voice guidance, natural-language spatial search ("gas stations along my route"), KML/KMZ import, GPS tracking, an admin panel for pipeline management, and TLS via Tailscale.

For the full feature set and screenshots, see [README.md](../README.md). For the install path, [SETUP.md](SETUP.md). The remainder of this document is about the *process*.
```

- [ ] **Step 3: Substitute the real numbers from Step 1 into the table**

- [ ] **Step 4: Voice check**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/PROCESS.md
```

Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add docs/PROCESS.md
git commit -m "$(cat <<'EOF'
docs(process): PROCESS.md §1 — numbers + intro

Per spec §6.3. Sets up the meta-story doc with header, intro
paragraph, and the headline numbers table. Subsequent sections
land in tasks 3.2–3.7.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.2: PROCESS.md §2 — The workflow + worked example

**Files:**
- Modify: `docs/PROCESS.md` (append §2)

- [ ] **Step 1: Pick the worked-example feature**

The example should be a *fully-shipped* feature that went through the entire workflow. Best candidates from the spec/plan archive:
- Voice picker (shipped 2026-04-21, full brainstorm + 5-round adversarial + execute)
- Public lands (shipped 2026-04-09, full cycle)
- NAIP imagery (shipped 2026-04-09, full cycle)

Recommended: **Voice picker.** It's compact, the artifact is recognizable to a non-GIS reader, and the spec/plan/execute trail is well-documented.

- [ ] **Step 2: Draft §2**

```markdown
## 2. The workflow

Every non-trivial feature went through the same loop:

1. **Brainstorm** in a structured skill (`superpowers:brainstorming`). Defines the audience, constraints, and 2-3 candidate approaches. Produces a spec document committed to `docs/superpowers/specs/`.
2. **Adversarial spec review.** Multiple Claude agents review the spec in parallel, each with a different attack angle (correctness, edge cases, threading, performance, security). Findings classified CRITICAL / MAJOR / MINOR. Spec revised to v2 (or v3 after a final Codex pass — see §3).
3. **Implementation plan.** Spec is decomposed into bite-sized TDD tasks (~2-5 minutes each), saved to `docs/superpowers/plans/`. Tasks specify file paths, code, expected test output, and commit messages.
4. **Subagent execution.** A controller agent dispatches a fresh subagent per task. The subagent reads the plan, executes the task, commits, and returns. The controller reviews the diff before dispatching the next.
5. **Field verification.** Where applicable (frontend, GPS, navigation), the human user takes the change for a real-world test before merge.

### Worked example: voice picker

The "voice picker" feature lets users choose which TTS voice the turn-by-turn navigation uses. End-to-end:

| Step | Date | Artifact |
|---|---|---|
| Brainstorm | 2026-04-20 | [`docs/superpowers/specs/2026-04-21-nav-voice-picker-design.md`](superpowers/specs/2026-04-21-nav-voice-picker-design.md) |
| Adversarial review (5 rounds: 4× Sonnet + 1× Codex) | 2026-04-20 | [`dev/adversarial/2026-04-20-voice-picker-*.md`](../dev/adversarial/) |
| Spec v2 incorporating findings | 2026-04-20 | (same path, revised in place) |
| Implementation plan (23 tasks) | 2026-04-20 | [`docs/superpowers/plans/2026-04-21-nav-voice-picker-plan.md`](superpowers/plans/2026-04-21-nav-voice-picker-plan.md) |
| Phase 0 execution (3 tasks) | 2026-04-20 | 3 commits on `dev` |
| Phases 1-5 execution (20 tasks) | 2026-04-21 | 20 commits on `dev` |
| UX refactor after field test | 2026-04-21 | "Working now" — Cameron |

Total elapsed: ~36 hours from "let's build this" to "Cameron confirmed working in the field." The agent execution accounted for ~12 of those hours; the rest was waiting for human review at workflow checkpoints.

The full receipts are in the linked artifacts. A reader who wants to see what an agent-built feature spec looks like can open the spec document above and read it end-to-end (~2,000 lines for the voice picker).
```

- [ ] **Step 3: Voice check + commit**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/PROCESS.md
git add docs/PROCESS.md
git commit -m "$(cat <<'EOF'
docs(process): PROCESS.md §2 — workflow + voice-picker worked example

Walks the brainstorm → adversarial → plan → execute loop and grounds
it in the voice picker's actual artifact trail (spec, adversarial
review, plan, commits). Reader can click through to see what an
agent-built feature looks like at each step.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.3: PROCESS.md §3 — Adversarial review patterns

**Files:**
- Modify: `docs/PROCESS.md` (append §3)

- [ ] **Step 1: Draft §3**

```markdown
## 3. Adversarial review patterns

A spec produced by one agent has the same blind spots as the agent that produced it. Adversarial review — multiple agents reading the spec, each told to find what's wrong — closes most of those blind spots before code is written.

### What each model is good at finding

In the patterns observed across 41 specs:

- **Claude Sonnet** (parallel rounds R1-R4) catches the most findings overall: missing edge cases, contract violations between modules, inconsistent state machines, unclear failure modes. Sonnet is fast and cheap enough to run 4 parallel reviewers per spec.
- **Claude Opus** is reserved for the highest-stakes specs (long, cross-cutting, or destined for production). Opus catches subtler reasoning errors and is more reliable on novel problem domains.
- **OpenAI Codex** (R5) catches things the Claude family systematically misses. The recurring pattern: Codex finds issues at module boundaries (where one team's mental model meets another's) and in places where the specification is internally consistent but factually wrong about an external system. Several specs were marked spec-v2-ready after R1-R4 only to have Codex flag a CRITICAL issue in R5. The cost of running Codex is small relative to the cost of shipping a critical bug found in the field.

### A concrete pattern: the ruler spec

The ruler/measurement tool spec went through:
- R1-R4 (parallel Sonnet): 10 CRITICAL findings, mostly about geodesy edge cases and elevation tile cancellation
- Spec revised to v2
- R5 (Codex): 1 CRITICAL finding the Sonnet rounds all missed — an editing-state click-leakage bug at the integration boundary between the ruler and the existing app's click handler

That R5 finding alone justified the entire round. See [`docs/superpowers/specs/2026-04-24-ruler-design.md`](superpowers/specs/2026-04-24-ruler-design.md).
```

- [ ] **Step 2: Voice check + commit**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/PROCESS.md
git add docs/PROCESS.md
git commit -m "$(cat <<'EOF'
docs(process): PROCESS.md §3 — adversarial review patterns

What Sonnet, Opus, and Codex are each good at finding, with a
concrete example (ruler spec R5 catching what 4 Sonnet rounds missed).

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.4: PROCESS.md §4 — Subagent orchestration

**Files:**
- Modify: `docs/PROCESS.md` (append §4)

- [ ] **Step 1: Draft §4**

```markdown
## 4. Subagent orchestration

The execution phase of every plan is run by subagents — fresh agent instances dispatched per task by a controller agent. This is what makes a 23-task plan ship in hours instead of days.

Three discipline points kept this from sliding into chaos:

### Agent monikers

Every commit carries an `Agent: <moniker>` trailer. Monikers are single-word lowercase plant/animal/geographic names (`tinaja`, `manzanita`, `cholla`, `pinyon`). They serve two purposes:

- **Forensics.** When something goes wrong (mysterious commit, regression, unclear authorship), `git log --grep="^Agent: <moniker>"` returns the full session trail. Without monikers, a multi-agent commit graph is unreadable.
- **Collision detection.** Subagents pick their own monikers and pass them down. A simple pre-flight `git log --grep="^Agent: " --format="%(trailers:key=Agent,valueonly)" | sort -u` catches collisions before they pollute the commit graph.

### Branch hygiene

Geographica's policy bans `git worktree` after two near-miss incidents in 2026-04 where subagents `cd`'d out of a worktree and performed destructive operations on the main checkout's branch. (See [`docs/pitfalls/implementation-pitfalls.md`](pitfalls/implementation-pitfalls.md) §14.) All branch work happens via `git checkout` in the main repo. Subagent prompts include a pre-flight `pwd` and `git branch --show-current` assertion.

### Destructive command ban

The same incident category produced an explicit ban on destructive git commands (`git reset --hard`, `git push --force`, `git checkout -- .`, `git clean -fd`, `--no-verify`, `git commit --amend` on shared commits, etc.). The full list and rationale are in [`CLAUDE.md`](../CLAUDE.md) under "Git workflow — destructive commands are BANNED." Subagents inherit this rule and surface a question to the user rather than running these commands.

These three rules are why a 932-commit, 17-agent project has a clean reflog and no bisect-blocking holes in its history.
```

- [ ] **Step 2: Voice check + commit**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/PROCESS.md
git add docs/PROCESS.md
git commit -m "$(cat <<'EOF'
docs(process): PROCESS.md §4 — subagent orchestration discipline

Monikers, branch hygiene (no worktrees), destructive-command ban —
the three rules that kept a 17-agent commit graph readable.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.5: PROCESS.md §5 — What this enables (and what it doesn't)

**Files:**
- Modify: `docs/PROCESS.md` (append §5)

- [ ] **Step 1: Draft §5**

```markdown
## 5. What this enables (and what it doesn't)

An honest read on where AI-orchestrated development worked and where it didn't.

### Worked well

- **Full-cycle features under good specs.** When a feature had a clear spec and a clean adversarial review, the agent team shipped it end-to-end with high reliability. The voice picker (§2), public lands layer, NAIP imagery acquisition, and the entire admin panel followed this pattern.
- **Repetitive grunt work.** Cross-cutting refactors, exhaustive test fixtures, and porting one pattern across many files are all places where parallel subagents shine. The cost of dispatching N subagents is roughly linear; the wall-clock improvement is roughly N×.
- **Bug hunts.** Multi-agent bug-hunt cycles (3 hunters in parallel + cross-validation) consistently surface real bugs that single-agent passes miss. Most CRITICAL findings since project start came from these cycles, not from runtime failures.
- **Documentation generation from artifacts.** This document, the README overhaul plan, the cost methodology — all written by agents working from on-disk receipts. The discipline of "every claim must point at a verifiable artifact" makes this trustworthy.

### Worked poorly

- **Visual polish.** Agents render layouts that work but rarely render layouts that are *beautiful*. Where the README was visually upgraded (favicon banner, screenshot framing, OG image composition), the human had to decide what looked right; the agent's role was execution, not aesthetic judgment.
- **Ambiguous specs.** When the spec contained any ambiguity — including phrases like "appropriate handling" or "as needed" — the agent execution amplified the ambiguity into divergent implementations across tasks. The fix is not "smarter agents"; it's "stricter specs."
- **Tasks requiring cross-task state.** Subagents are isolated by design. Any task requiring "remember what the previous task did" has to put that state in the plan or in committed code. When the plan tried to chain implicit state, the result was rework.
- **Aesthetic copy.** Marketing prose, narrative tone, and persuasive writing are still better as a human-led pass with the agent as a drafting assistant. The voice rule in this document set (no first-person) is itself an artifact of that lesson — human-supervised stylistic constraint.

### Implications for transferring to higher-stakes work

- **Process rigor is the multiplier.** A worse model with this loop beats a better model with no loop. The brainstorm → adversarial → plan → execute discipline matters more than which Claude tier is invoked at each step.
- **Spec quality predicts everything downstream.** The cost of a thorough spec + adversarial review is small; the cost of skipping that step compounds across the whole feature.
- **Human attention is the scarce resource.** Agents are cheap; the time to read what they produced and decide whether it's right is not. Any process change that reduces human-review burden (clearer task boundaries, better automated checks, smaller PRs) is worth more than any change that makes the agent itself faster.
```

- [ ] **Step 2: Voice check + commit**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/PROCESS.md
git add docs/PROCESS.md
git commit -m "$(cat <<'EOF'
docs(process): PROCESS.md §5 — what works, what doesn't, transfer notes

Honest read on the boundaries: full-cycle features under good specs
work; visual polish and ambiguous specs do not. Process rigor > model
choice. Implications section frames how to transfer the methodology to
higher-stakes work.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.6: PROCESS.md §6 — Companion utility

**Files:**
- Modify: `docs/PROCESS.md` (append §6)

- [ ] **Step 1: Lift the meta-story portion of "Companion data utility"**

From `dev/notes/README-pre-overhaul.md` (the saved old README), extract the *why* and *origin* portion of §"Companion data utility" — the part that talks about why a separate cross-platform utility was needed, not the operational instructions (which moved to MANUAL_SETUP.md in Task 1.3).

- [ ] **Step 2: Add §6 frame**

```markdown
## 6. Companion utility

Geographica's data acquisition (NAIP imagery, OSM extracts, elevation tiles) is CPU- and memory-intensive. Running it on a Pi 5 — the deployment target — works but takes a long time. To shorten the install path for users who have a faster workstation handy, a companion data utility was built as a separate cross-platform desktop tool that processes data fast and SCPs the result to the Pi.

The companion lives in [its own repo](https://github.com/cameronzucker/geographica-companion) and is itself a worked example of agent-team development: separate brainstorm, separate spec, separate implementation plan, separate adversarial review. The lesson reinforced from building it — agent-team workflow generalizes across project boundaries; the discipline transfers, even when the codebase doesn't.

[ Operational details — how to install and use the companion — live in MANUAL_SETUP.md §Companion data utility. ]
```

- [ ] **Step 2: Voice check + commit**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/PROCESS.md
git add docs/PROCESS.md
git commit -m "$(cat <<'EOF'
docs(process): PROCESS.md §6 — companion utility as second worked example

Frames the companion repo as a second worked example of the same
agent-team workflow generalizing across a different codebase. Operational
how-to lives in MANUAL_SETUP.md (per the doc-split decision).

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3.7: PROCESS.md §7 — References + final review

**Files:**
- Modify: `docs/PROCESS.md` (append §7)

- [ ] **Step 1: Append §7**

```markdown
## 7. References

The complete trail of receipts:

- [`docs/superpowers/specs/`](superpowers/specs/) — every brainstormed feature spec, with adversarial-review revisions
- [`docs/superpowers/plans/`](superpowers/plans/) — every implementation plan, broken into TDD tasks
- [`dev/implementation-log.md`](../dev/implementation-log.md) — chronological log of major work items
- [`dev/adversarial/`](../dev/adversarial/) — adversarial review outputs by feature and date
- [`CHANGELOG.md`](../CHANGELOG.md) — release-by-release feature deltas
- [`scripts/audit_inference_cost.py`](../scripts/audit_inference_cost.py) — the cost-audit script (see [COST_METHODOLOGY.md](COST_METHODOLOGY.md))

For the artifact itself (what the project does, how to install), see [README.md](../README.md) and [SETUP.md](SETUP.md).
```

- [ ] **Step 2: Verify total document length is in spec budget**

```bash
wc -l /home/administrator/Code/geographica/docs/PROCESS.md
```

Expected: 230-280 lines (close to the spec's ~250 estimate).

- [ ] **Step 3: Voice check (final pass on the whole document)**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/docs/PROCESS.md
```

Expected: no output. If matches found, restructure those sentences before committing.

- [ ] **Step 4: Commit**

```bash
git add docs/PROCESS.md
git commit -m "$(cat <<'EOF'
docs(process): PROCESS.md §7 — references; PROCESS.md complete

The full receipts list (specs/, plans/, implementation-log, adversarial/,
CHANGELOG, audit script). PROCESS.md is now content-complete per spec
§6.3 — 7 sections, ~250 lines, declarative voice throughout.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 4 — README content

Goal: fill in the prose blocks in `README.md` that Phase 1 stubbed with `<!-- TODO: Phase 4 ... -->` markers. After this phase, the README is content-complete and only awaits screenshot embeds.

---

### Task 4.1: Features section — 4 thematic groups

**Files:**
- Modify: `README.md` (Features section, marked `<!-- TODO: Phase 4 Task 4.1 -->`)
- Reference: `dev/notes/README-pre-overhaul.md` (for original feature-bullet copy)

- [ ] **Step 1: Locate the TODO marker and replace with grouped features**

Use the spec §5.1 grouping (4 thematic groups, each with one inline screenshot placeholder). Group bullets are lifted from the old README's `## Features` section but reorganized into thematic blocks. Inline screenshot embeds are placeholder paths that Task 5.10 will populate.

```markdown
## Features

<p align="center">
<img src="docs/screenshots/3d-terrain.png" alt="3D terrain with hillshade and exaggeration slider" width="600" />
<br>
<em>3D terrain with hillshade — one of three rendering modes for any region.</em>
</p>

### Mapping & imagery

<img src="docs/screenshots/public-lands.png" alt="Public lands layer with agency-colored fills and tribal stripes" width="500" align="right" />

- **Vector basemaps** — three themes (Positron light, Dark Matter dark, Hybrid imagery+roads) with house-number labels.
- **Aerial imagery** — five acquisition modes (USGS Direct, NOAA NAIP, National Map ImageServer, USGS M2M API, BYO GeoTIFF). Per-source toggles, opacity slider, dynamic basemap restyling when imagery is active.
- **Public lands layer** — BLM, National Forest, National Park, Fish & Wildlife, Military, Bureau of Reclamation, Tribal, State Trust, and Wilderness boundaries. Agency-colored fills, tribal-boundary diagonal stripes, full legend.
- **3D terrain** — hillshade overlay, adjustable exaggeration slider, free-look camera (pitch/bearing control).

<br clear="right" />

### Spatial intelligence

<img src="docs/screenshots/voice-search.png" alt="Voice search active with result list and numbered map pins" width="500" align="right" />

- **Natural-language spatial search** — "nearest gas station", "hospitals near me", "gas stations along my route", "fuel every 50 miles", "gas stations in Flagstaff", "restaurants in Phoenix along my route". Distance-ranked results, numbered map pins, city-aware geocoding.
- **Voice search** — push-to-hold mic button for hands-free queries via Whisper (base.en, CPU). Requires HTTPS.
- **OSM POI search** — commercial amenities (fuel, food, lodging, pharmacy, grocery) and public-land boundaries extracted from OSM data.
- **Geocoding** — Nominatim-backed search for addresses, cities, landmarks.
- **POI search** — GNIS gazetteer with full-text search.

<br clear="right" />

### Navigation & GPS

<img src="docs/screenshots/mobile-nav.png" alt="In-vehicle navigation on phone, GPS following, maneuver banner active" width="280" align="right" />

- **Turn-by-turn navigation** — voice guidance, off-route detection, dead reckoning.
- **Multi-stop waypoint routing** — map-click point selection for car, bicycle, and pedestrian profiles.
- **Live GPS** — hardware GPS streaming over WebSocket with accuracy circle display.
- **KML/KMZ import** — drag-and-drop file overlay with layer management panel and IndexedDB session persistence.
- **Coordinate display** — Maidenhead grid locator and MGRS in addition to lat/lon.
- **Imperial and metric units** — switchable distance/elevation units.
- **Print/export directions** — Mapquest-style printable page.

<br clear="right" />

### Operations & admin

<img src="docs/screenshots/admin-pipeline.png" alt="Admin panel pipelines tab with 7 source cards and minimap bbox selector" width="500" align="right" />

- **Admin config panel** (localhost-only, separated from main app) — 4-tab layout with Dashboard (service health, disk/TLS info), Pipelines (7-source card grid with MapLibre minimap bbox selection), Inventory (imagery coverage map with clustered markers), Settings (credential keyring, TLS config, STT status).
- **Pipeline management** — start/cancel imagery (5 modes), elevation, public lands, and OSM POI extraction from the browser, with phase-aware progress tracking and quad-level deduplication.
- **ATAK integration** — serves as a WMS map source for TAK clients.
- **TLS support** — three modes (HTTP, HTTPS self-signed, Tailscale Let's Encrypt).
- **Credential security** — API keys stored in GNOME Keyring via host-side daemon, shared with containers over tmpfs (no plaintext credential files).
- **No build step** — vanilla JS + MapLibre GL JS frontend, no bundler required.

<br clear="right" />
```

- [ ] **Step 2: Verify the inline images use the right paths**

```bash
grep -oE "docs/screenshots/[a-z-]+\\.png" /home/administrator/Code/geographica/README.md | sort -u
```

Expected exactly: `docs/screenshots/3d-terrain.png`, `docs/screenshots/admin-pipeline.png`, `docs/screenshots/mobile-nav.png`, `docs/screenshots/public-lands.png`, `docs/screenshots/voice-search.png` (5 unique).

- [ ] **Step 3: Verify the TODO marker is gone**

```bash
grep -n "TODO: Phase 4 Task 4.1" /home/administrator/Code/geographica/README.md
```

Expected: no output.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): Features section — 4 thematic groups w/ inline shots

Per spec §5.1: Mapping & imagery / Spatial intelligence / Navigation &
GPS / Operations & admin, each with one inline screenshot placeholder.
3D terrain shot anchors the section open. Image paths point at
docs/screenshots/ — actual PNGs land in Task 5.10.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.2: Architecture section — Mermaid diagram

**Files:**
- Modify: `README.md` (Architecture section)

- [ ] **Step 1: Replace the TODO marker with the Mermaid diagram + caption**

```markdown
## Architecture

\`\`\`mermaid
flowchart LR
    Browser["🌐 Browser"]
    NGINX["NGINX :8093"]
    NGINX_CFG["NGINX :8097<br/>(localhost only)"]
    TS["TileServer GL :8090<br/>vector / raster / elevation tiles"]
    VAL["Valhalla :8094<br/>routing engine"]
    NOM["Nominatim :8092<br/>geocoding (PostgreSQL)"]
    SRCH["Search :8096<br/>spatial search + admin API"]
    STT["STT :8098<br/>Whisper speech-to-text"]
    GPS["GPS :8095<br/>WebSocket GPS relay"]
    PIPE["Pipeline (on-demand)<br/>imagery / elevation / OSM POIs"]

    Browser --> NGINX
    NGINX --> TS
    NGINX --> VAL
    NGINX --> NOM
    NGINX --> SRCH
    NGINX --> STT
    NGINX --> GPS

    NGINX_CFG --> SRCH
    NGINX_CFG --> TS

    SRCH -.->|triggers| PIPE
    PIPE -.->|writes tiles| TS
\`\`\`

Seven persistent Docker Compose services plus an on-demand pipeline container, with per-container memory limits to prevent OOM on constrained hardware. NGINX reverse-proxies all services behind a single port with URL rewriting for TileServer GL style/TileJSON endpoints. The configuration NGINX (port 8097) is bound to localhost only and serves the admin panel + pipeline-management API; the main NGINX (port 8093) serves the user-facing app.

The on-demand pipeline container runs imagery acquisition, elevation tile downloads, and OSM POI extraction. It writes new tiles into the data volume, and TileServer GL hot-reloads its config to pick them up without a restart.
```

- [ ] **Step 2: Verify the Mermaid block is well-formed**

```bash
grep -A 30 '```mermaid' /home/administrator/Code/geographica/README.md | head -35
```

Expected: a clean flowchart definition that closes with `\`\`\``.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): Architecture — Mermaid diagram replaces ASCII

GitHub renders \`\`\`mermaid\`\`\` blocks natively. Diagram preserves
the 7-service layout from the previous ASCII version, adds explicit
on-demand pipeline edges (dotted), and labels the dual-NGINX boundary
(8093 user-facing vs 8097 admin localhost-only).

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.3: Header — favicon banner + badge row

**Files:**
- Modify: `README.md` (top of file, header section)

- [ ] **Step 1: Replace the header TODO marker with the favicon-anchored heading + tagline + badges**

```markdown
<img src="docs/geographica_favicon.png" width="80" height="80" align="left" alt="Geographica favicon" />

# Geographica

**Offline-first GIS platform for field operations on disconnected networks.** A complete mapping stack — vector basemaps, aerial imagery, terrain, routing, geocoding, GPS — running on a single Raspberry Pi 5.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/github/v/release/cameronzucker/geographica)](CHANGELOG.md)
[![CI](https://github.com/cameronzucker/geographica/actions/workflows/ci.yml/badge.svg)](https://github.com/cameronzucker/geographica/actions)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](#)
[![Built in](https://img.shields.io/badge/built_in-19_days-d29922.svg)](docs/PROCESS.md)
[![Agents](https://img.shields.io/badge/agents-17-7c3aed.svg)](docs/PROCESS.md)

<br clear="left" />
```

- [ ] **Step 2: Verify badges resolve**

Visit each badge URL in a browser (or `curl -sI` it) and confirm 200/302. The two custom badges (`built_in-19_days` and `agents-17`) are static shields.io URLs that render anything as a badge — no backend dependency.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): header — favicon banner + standard + meta-story badges

Inline 80px favicon image left of the heading; tagline directly under;
6 badges (license, version, CI, python, built-in-19-days, agents-17).
The two custom badges link to PROCESS.md so a curious reader can
verify the claim.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4.4: Remaining README sections — callout, hardware, get-started, project layout

**Files:**
- Modify: `README.md` (multiple TODO markers)

- [ ] **Step 1: Fill in the "How it was built" callout**

Replace the meta-callout TODO marker with:

```markdown
> **How it was built:** 19 days. One engineer plus a team of Claude agents working under structured agent-orchestration patterns — brainstorm, adversarial review, TDD execution by parallel sub-agents. Inference cost: ~$2,500 in API-equivalent model output, paid as a Claude Max subscription (~$200/mo). [Read the process →](docs/PROCESS.md) · [Cost methodology →](docs/COST_METHODOLOGY.md)
```

- [ ] **Step 2: Fill in the one-paragraph elaboration**

Replace the TODO marker (after the heading, before the hero shot) with:

```markdown
Built for [AREDN](https://www.arednmesh.org/) mesh networks and field teams operating without cloud connectivity. Acquire data once on a connected workstation, then deploy anywhere — wilderness, disaster recovery, off-grid bases, or mesh-network coverage areas. After initial data acquisition, no internet connection is required.
```

- [ ] **Step 3: Fill in the Hardware requirements section**

Lift the two existing tables from `dev/notes/README-pre-overhaul.md` §"Hardware requirements" (lines 42-77) into the README's Hardware requirements section. Verbatim — these tables are already correct.

- [ ] **Step 4: Fill in the Get started section**

```markdown
## Get started

For a guided setup experience, use the wizard:

\`\`\`bash
git clone https://github.com/cameronzucker/geographica.git
cd geographica
sudo ./bootstrap.sh    # install system prerequisites
# log out and back in so the docker group takes effect, then:
./setup.sh             # launch browser-based setup wizard
\`\`\`

Then open http://localhost:8099 to walk the wizard.

For step-by-step setup → [docs/SETUP.md](docs/SETUP.md)
For manual / advanced setup → [docs/MANUAL_SETUP.md](docs/MANUAL_SETUP.md)
```

- [ ] **Step 5: Fill in the Project layout section**

```markdown
## Project layout

\`\`\`
geographica/
├── docker-compose.yml     # 7 persistent services + on-demand pipeline
├── services/              # GPS, search, STT (FastAPI services)
├── scripts/               # offline data pipeline (imagery, elevation, POIs)
├── frontend/              # vanilla JS + MapLibre GL JS app
├── nginx/                 # reverse-proxy config
├── tileserver/            # TileServer GL config and styles
├── setup/                 # browser-based setup wizard
├── docs/                  # SETUP.md, MANUAL_SETUP.md, PROCESS.md, COST_METHODOLOGY.md
├── bootstrap.sh           # system prerequisites (sudo)
├── setup.sh               # wizard launcher
└── data → /srv/geographica/data/   # symlink (gitignored): MBTiles, PBF, SQLite
\`\`\`
```

- [ ] **Step 6: Verify all TODO markers are now resolved**

```bash
grep -n "TODO" /home/administrator/Code/geographica/README.md
```

Expected: no output (the only remaining TODO would be Task 5.10's hero-screenshot embed, which Phase 4 is leaving for Phase 5).

Wait — re-check. The hero screenshot is `<!-- TODO: Phase 5 Task 5.10 -->`. So the grep should return only that one line.

```bash
grep -n "TODO" /home/administrator/Code/geographica/README.md
```

Expected: exactly **1 match** — the hero-screenshot TODO at the top.

- [ ] **Step 7: Verify line count is roughly in budget**

```bash
wc -l /home/administrator/Code/geographica/README.md
```

Expected: ~180-220 lines (close to spec's ~210 estimate; will grow slightly when hero embed lands).

- [ ] **Step 8: Voice check on the entire README**

```bash
grep -nE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" /home/administrator/Code/geographica/README.md
```

Expected: no output.

- [ ] **Step 9: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): callout, hardware, get-started, project-layout content

Fills the remaining Phase-4 TODO markers in README.md. After this
commit only the hero-screenshot embed (Phase 5 Task 5.10) is unfilled.
Line count ~180-220, in spec budget. Voice rule holds throughout.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 5 — Screenshot capture, post-processing, embedding

Goal: produce the 1 hero + 5 inline + 3 gallery PNGs and embed them. Mixed strategy per spec §4.8: Playwright for everything that doesn't need GPS / in-vehicle context; Cameron captures the GPS-pinned hero and the mobile-in-vehicle shot.

**Pre-flight check:** Live stack must be running. Run `docker compose ps` and confirm 7 services are `Up (healthy)` before any task in this phase.

---

### Task 5.1: Write Playwright capture script

**Files:**
- Create: `scripts/capture_readme_screenshots.py`

The script is modular: one function per shot. Each function navigates the browser, sets up the required state (selects layer toggles, clicks tabs, runs a search), waits for tiles/UI to settle, and saves to the target path. Subsequent tasks (5.2–5.6) invoke individual shot functions; this task just lays the framework.

- [ ] **Step 1: Write the script skeleton**

```python
# scripts/capture_readme_screenshots.py
"""
Capture README screenshots from the live Geographica stack.

Each function captures one shot. Functions are independent — invoke any
subset via --shots argument:

  python3 scripts/capture_readme_screenshots.py --shots 3d-terrain,voice-search

Pre-flight: live stack must be running (`docker compose ps` shows 7 services
Up (healthy)). Default base URL is http://localhost:8093.
"""
import argparse
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
GALLERY_DIR = OUT_DIR / "gallery"
DEFAULT_URL = "http://localhost:8093"
ADMIN_URL   = "http://localhost:8097"

VIEWPORT = {"width": 1280, "height": 800}
PHONE_VIEWPORT = {"width": 390, "height": 844}  # iPhone 14 Pro proportions


async def shot_3d_terrain(page, url):
    """3D terrain w/ hillshade + exaggeration slider visible."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Open Layers panel
    await page.locator("button[aria-label='Layers']").click()
    # Toggle 3D terrain
    await page.locator("text=3D Terrain").click()
    # Show exaggeration slider
    await page.wait_for_timeout(2000)  # let tiles render
    await page.screenshot(path=str(OUT_DIR / "3d-terrain.png"), full_page=False)


async def shot_voice_search(page, url):
    """Voice search active + result list ('gas stations along route') + map pins."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Type query directly (skip mic since Playwright can't easily mock audio input)
    await page.locator("input[type='search']").fill("gas stations along my route")
    await page.locator("input[type='search']").press("Enter")
    await page.wait_for_selector(".search-result", timeout=10000)
    await page.wait_for_timeout(1500)
    await page.screenshot(path=str(OUT_DIR / "voice-search.png"), full_page=False)


async def shot_public_lands(page, url):
    """Public lands layer with agency-colored fills + tribal stripes + legend."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    await page.locator("button[aria-label='Layers']").click()
    await page.locator("text=Public Lands").click()
    # Pan to Arizona/Utah border for good public-lands density
    await page.wait_for_timeout(2000)
    await page.screenshot(path=str(OUT_DIR / "public-lands.png"), full_page=False)


async def shot_admin_pipeline(page, url):
    """Admin → Pipelines tab — 7 source cards + minimap + active progress."""
    await page.goto(ADMIN_URL)
    await page.wait_for_load_state("networkidle")
    await page.locator("text=Pipelines").click()
    await page.wait_for_timeout(1500)
    await page.screenshot(path=str(OUT_DIR / "admin-pipeline.png"), full_page=False)


async def shot_setup_wizard(page, url):
    """Setup wizard step 3 — clean dark mode, progress dots, professional."""
    await page.goto("http://localhost:8099/step/3")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    await page.screenshot(path=str(GALLERY_DIR / "setup-wizard.png"), full_page=False)


async def shot_kmz_overlay(page, url):
    """Drag-drop KMZ overlay + layer panel + custom icons rendered."""
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    # Trigger file input directly
    await page.set_input_files("input[type='file'][accept*='kmz']", "docs/Ham Radio Deployment Sites.kmz")
    await page.wait_for_timeout(2500)  # let icons load
    await page.screenshot(path=str(GALLERY_DIR / "kmz-overlay.png"), full_page=False)


async def shot_imagery_before_after(page, url):
    """Side-by-side: basemap only vs NAIP overlay enabled. Two captures + composited."""
    # Capture "before" (basemap only)
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1500)
    before = await page.screenshot(full_page=False)

    # Toggle NAIP imagery
    await page.locator("button[aria-label='Layers']").click()
    await page.locator("text=NOAA NAIP").click()
    await page.wait_for_timeout(3000)  # let imagery tiles load
    after = await page.screenshot(full_page=False)

    # Composite side-by-side via Pillow
    from PIL import Image
    import io
    bimg = Image.open(io.BytesIO(before))
    aimg = Image.open(io.BytesIO(after))
    composite = Image.new("RGB", (bimg.width + aimg.width + 8, max(bimg.height, aimg.height)), "white")
    composite.paste(bimg, (0, 0))
    composite.paste(aimg, (bimg.width + 8, 0))
    composite.save(GALLERY_DIR / "imagery-before-after.png")


SHOTS = {
    "3d-terrain":            (shot_3d_terrain,            VIEWPORT),
    "voice-search":          (shot_voice_search,          VIEWPORT),
    "public-lands":          (shot_public_lands,          VIEWPORT),
    "admin-pipeline":        (shot_admin_pipeline,        VIEWPORT),
    "setup-wizard":          (shot_setup_wizard,          VIEWPORT),
    "kmz-overlay":           (shot_kmz_overlay,           VIEWPORT),
    "imagery-before-after":  (shot_imagery_before_after,  VIEWPORT),
}


async def run(shots_to_capture, url):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        for name in shots_to_capture:
            if name not in SHOTS:
                print(f"  ⚠ unknown shot: {name}; valid: {','.join(SHOTS)}")
                continue
            shot_fn, viewport = SHOTS[name]
            ctx = await browser.new_context(viewport=viewport, device_scale_factor=2)
            page = await ctx.new_page()
            print(f"  → capturing {name} …")
            try:
                await shot_fn(page, url)
                print(f"     ✓ saved")
            except Exception as e:
                print(f"     ✗ FAILED: {e}")
            await ctx.close()
        await browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shots", default=",".join(SHOTS),
                        help="Comma-separated shot names")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args()
    asyncio.run(run(args.shots.split(","), args.url))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Test the script structure (don't capture yet)**

```bash
cd /home/administrator/Code/geographica && python3 scripts/capture_readme_screenshots.py --shots nonexistent
```

Expected: prints "unknown shot" warning and exits cleanly.

- [ ] **Step 3: Commit**

```bash
git add scripts/capture_readme_screenshots.py
git commit -m "$(cat <<'EOF'
feat(scripts): Playwright README screenshot capture framework

Modular per-shot functions for the 4 desktop inline shots + 3 gallery
shots. Each function navigates the live stack, sets up state, captures.
Supports --shots subset selection so failing one shot doesn't block
the others.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Tasks 5.2 – 5.6: Capture each Playwright shot (one task per shot)

These five tasks are structurally identical. Each invokes the script for one shot, manually inspects the result, and either commits or iterates on the script if the shot is unusable.

**Tasks 5.2–5.6 are parallelizable** if dispatched as independent subagents — each shot is independent. Sequential is also fine (probably ~5 minutes total).

For each shot in `[3d-terrain, voice-search, public-lands, admin-pipeline]` (inline) and `[setup-wizard, kmz-overlay, imagery-before-after]` (gallery):

- [ ] **Step 1: Capture**

```bash
cd /home/administrator/Code/geographica
python3 scripts/capture_readme_screenshots.py --shots <shot-name>
```

- [ ] **Step 2: Visually inspect the PNG**

Open `docs/screenshots/<shot-name>.png` (or `gallery/<shot-name>.png`) in an image viewer. Acceptance:
- The intended UI element is visible and clearly the focal point
- No console errors or empty placeholders are showing
- Tiles have fully loaded (no pixelated/half-rendered tiles)
- The frame is roughly centered on what matters

If the shot is unusable: revise `scripts/capture_readme_screenshots.py` (longer wait, different navigation, different viewport), recapture, repeat until acceptable. **Per spec §4.8, fall back to manual capture if Playwright cannot produce an acceptable shot for a given function** — only screenshots are at stake.

- [ ] **Step 3: Commit the PNG**

```bash
git add docs/screenshots/<shot-name>.png      # or gallery/<shot-name>.png
git commit -m "$(cat <<'EOF'
docs(screenshots): <shot-name> — captured from live stack

Captured via scripts/capture_readme_screenshots.py against the running
dev stack. <one-line acceptance note: e.g., "shows 3D terrain at zoom
13 over Flagstaff with exaggeration slider visible at left">.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.7: Manual capture — hero everything-shot + mobile in-vehicle nav

**Files:**
- Create: `docs/screenshots/hero-everything.png` (manual)
- Create: `docs/screenshots/mobile-nav.png` (manual)

This task is **driven by Cameron**, not by an agent. The agent's role is to (a) document the requirements, (b) confirm receipt of the PNGs, (c) verify they meet acceptance criteria, (d) commit them.

- [ ] **Step 1: Acceptance criteria (documented for Cameron)**

**Hero everything-shot** (`docs/screenshots/hero-everything.png`):
- Resolution: 1280×800 minimum (will be displayed at 600px wide in README; needs HiDPI)
- Content: a single screenshot of the live app showing simultaneously:
  - Vector basemap visible underneath
  - NAIP aerial imagery overlay enabled (transparency adjusted so both basemap and imagery are readable)
  - GPS pin visible on the map (real GPS fix preferred; demo pin acceptable)
  - Active turn-by-turn navigation route visible as a polyline
  - Maneuver banner at top of screen showing the next instruction
- Setting: any region with NAIP coverage (Flagstaff is a known-good area)
- File: PNG, no annotation

**Mobile in-vehicle nav** (`docs/screenshots/mobile-nav.png`):
- Resolution: native phone resolution (iPhone or Android), portrait
- Content: phone screenshot of the app in nav mode, with:
  - Maneuver banner visible at top
  - Map showing route + GPS following
  - Ideally captured while a passenger in a vehicle (real-world context); stationary acceptable
- File: PNG, no annotation (the phone-frame composite is added in Task 5.9)

- [ ] **Step 2: Wait for files**

When Cameron drops the two PNGs into `docs/screenshots/`, this task can advance. The implementer should NOT proceed past this step until both files exist.

```bash
ls -la /home/administrator/Code/geographica/docs/screenshots/hero-everything.png /home/administrator/Code/geographica/docs/screenshots/mobile-nav.png
```

Both files must exist and be > 100 KB.

- [ ] **Step 3: Verify each meets acceptance criteria**

Open each PNG in an image viewer. Walk the criteria from Step 1. If a shot is unacceptable, surface the gap to Cameron and ask for a retake.

- [ ] **Step 4: Commit**

```bash
git add docs/screenshots/hero-everything.png docs/screenshots/mobile-nav.png
git commit -m "$(cat <<'EOF'
docs(screenshots): hero everything-shot + mobile in-vehicle nav

Manual captures by Cameron — Playwright cannot produce shots that
require live GPS or in-vehicle context. Hero is the README's
above-the-fold anchor; mobile-nav is the inline shot for the
Navigation & GPS feature group.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.8: Post-process desktop screenshots — border + drop shadow

**Files:**
- Create: `scripts/postprocess_screenshots.py`
- Modify: PNGs in `docs/screenshots/` (in-place)

- [ ] **Step 1: Write the post-processing script**

```python
# scripts/postprocess_screenshots.py
"""
Apply visual framing to README screenshots.

Desktop shots: subtle 1px border (#d0d7de) + soft drop shadow.
Mobile shots: composite into a phone frame.

Idempotent: re-running on already-processed PNGs detects the framing
sentinel (a 1-pixel transparent stripe in the bottom-right) and skips.
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
GALLERY_DIR = OUT_DIR / "gallery"
PHONE_FRAME_PATH = OUT_DIR / "_phone_frame_template.png"  # downloaded once

DESKTOP_SHOTS = ["3d-terrain", "voice-search", "public-lands", "admin-pipeline", "hero-everything"]
GALLERY_SHOTS = ["setup-wizard", "kmz-overlay", "imagery-before-after"]
MOBILE_SHOTS = ["mobile-nav"]

BORDER_COLOR = (208, 215, 222, 255)  # GitHub muted border
SHADOW_OFFSET = (0, 8)
SHADOW_BLUR = 16
SHADOW_OPACITY = 64
PADDING = 24


def desktop_frame(input_path, output_path):
    """1px border + soft drop shadow on a transparent canvas."""
    src = Image.open(input_path).convert("RGBA")
    sw, sh = src.size

    canvas_w = sw + PADDING * 2
    canvas_h = sh + PADDING * 2 + SHADOW_OFFSET[1]
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # Draw shadow first
    shadow = Image.new("RGBA", (sw, sh), (0, 0, 0, SHADOW_OPACITY))
    shadow_blurred = shadow.filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    canvas.paste(shadow_blurred, (PADDING + SHADOW_OFFSET[0], PADDING + SHADOW_OFFSET[1]), shadow_blurred)

    # Draw the source image
    canvas.paste(src, (PADDING, PADDING), src)

    # Border (1px)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        [(PADDING, PADDING), (PADDING + sw - 1, PADDING + sh - 1)],
        outline=BORDER_COLOR,
        width=1,
    )

    canvas.save(output_path, optimize=True)
    print(f"  ✓ {input_path.name} → framed")


def phone_frame(input_path, output_path, frame_template=PHONE_FRAME_PATH):
    """Composite a phone screenshot into a phone-frame template."""
    if not frame_template.exists():
        # Fallback: just apply desktop_frame at portrait aspect
        print(f"  ⚠ phone frame template missing at {frame_template}; falling back to desktop frame")
        desktop_frame(input_path, output_path)
        return

    src = Image.open(input_path).convert("RGBA")
    frame = Image.open(frame_template).convert("RGBA")

    # Frame template should have a transparent rectangular cutout for the screen
    # Resize source to fit the cutout (assumes 9:19.5 ratio modern phone)
    cutout_w, cutout_h = frame.size  # template defines the target dims
    src_resized = src.resize((cutout_w, cutout_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    canvas.paste(src_resized, (0, 0), src_resized)
    canvas.paste(frame, (0, 0), frame)
    canvas.save(output_path, optimize=True)
    print(f"  ✓ {input_path.name} → phone-framed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots", default="all")
    args = parser.parse_args()

    targets = []
    if args.shots == "all":
        targets = (
            [(OUT_DIR / f"{s}.png", OUT_DIR / f"{s}.png", "desktop") for s in DESKTOP_SHOTS]
          + [(GALLERY_DIR / f"{s}.png", GALLERY_DIR / f"{s}.png", "desktop") for s in GALLERY_SHOTS]
          + [(OUT_DIR / f"{s}.png", OUT_DIR / f"{s}.png", "phone") for s in MOBILE_SHOTS]
        )
    # else: parse args.shots ...

    for inpath, outpath, kind in targets:
        if not inpath.exists():
            print(f"  ⚠ skipping (missing): {inpath.name}")
            continue
        if kind == "desktop":
            desktop_frame(inpath, outpath)
        elif kind == "phone":
            phone_frame(inpath, outpath)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run on the desktop + gallery shots**

```bash
cd /home/administrator/Code/geographica && python3 scripts/postprocess_screenshots.py --shots all
```

- [ ] **Step 3: Visually inspect each framed PNG**

Open each in an image viewer. Acceptance: subtle border visible; soft drop shadow on bottom + right; transparent canvas (so README rendering doesn't have a white outer rectangle).

- [ ] **Step 4: Commit script + framed PNGs together**

```bash
git add scripts/postprocess_screenshots.py docs/screenshots/*.png docs/screenshots/gallery/*.png
git commit -m "$(cat <<'EOF'
chore(screenshots): post-process desktop shots (border + drop shadow)

Pillow-based framing: 1px GitHub-muted border + soft drop shadow on
transparent canvas. Idempotent (safe to re-run). Mobile shots get
phone-frame composite in Task 5.9.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.9: Phone-frame composite for mobile screenshots

**Files:**
- Create: `docs/screenshots/_phone_frame_template.png` (transparent overlay phone frame)
- Modify: `docs/screenshots/mobile-nav.png` (in-place, framed)

- [ ] **Step 1: Acquire a phone-frame template PNG**

Two acceptable sources:
- Download a free phone-frame PNG from mockuphone.com (no signup required) and save as `docs/screenshots/_phone_frame_template.png`. Choose iPhone 14 Pro or similar.
- Generate via Pillow with simple rounded-rectangle bezel. Lower fidelity but no external dependency.

Recommended: download once. Add the file to git (it's an asset, not a build artifact).

- [ ] **Step 2: Re-run `postprocess_screenshots.py` so phone-frame composite runs**

```bash
cd /home/administrator/Code/geographica && python3 scripts/postprocess_screenshots.py --shots mobile-nav
```

The script's `phone_frame()` function should detect the now-present template and composite.

- [ ] **Step 3: Visually inspect**

Open `docs/screenshots/mobile-nav.png`. Acceptance: phone bezel visible around the screenshot; screenshot fills the cutout cleanly (no obvious scaling artifacts or misalignment).

- [ ] **Step 4: Commit template + framed mobile shot**

```bash
git add docs/screenshots/_phone_frame_template.png docs/screenshots/mobile-nav.png
git commit -m "$(cat <<'EOF'
chore(screenshots): phone-frame composite for mobile-nav shot

Adds the phone-frame template asset (downloaded from mockuphone.com)
and applies it to mobile-nav.png via postprocess_screenshots.py.
Mobile shots in the README now read as phone screenshots, not
arbitrary portrait images.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5.10: Embed the hero screenshot in README

**Files:**
- Modify: `README.md` (the last remaining `<!-- TODO: Phase 5 Task 5.10 -->` marker)

- [ ] **Step 1: Replace the hero TODO marker**

```markdown
<p align="center">
<img src="docs/screenshots/hero-everything.png" alt="Live map with NAIP imagery, GPS pin, and active turn-by-turn navigation route" width="640" />
</p>
```

- [ ] **Step 2: Verify no remaining TODO markers**

```bash
grep -n "TODO" /home/administrator/Code/geographica/README.md
```

Expected: no output. README is now content + asset complete.

- [ ] **Step 3: Render-check the README on github.com (or via gh-markdown preview tool)**

If `glow` is installed: `glow README.md`. Otherwise push to a draft branch and view on github.com.

Acceptance:
- Header layout: favicon + title on the same line
- Badge row visible directly under the title
- Hero image renders centered
- Mermaid block renders as a flowchart (not as a code fence)
- All four feature-group inline screenshots render with text wrapping correctly

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "$(cat <<'EOF'
docs(readme): embed hero screenshot — README content+asset complete

Replaces the last <!-- TODO --> marker in README.md with the centered
hero screenshot. Per Definition of Done §10 line 6: all screenshots
captured + post-processed + committed.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

# Phase 6 — OG image, cross-link audit, render verification

Goal: ship the social-share image, audit all cross-links across the doc set, and verify the Mermaid diagram and screenshots all render correctly on GitHub.

---

### Task 6.1: Composite the OG / social-share image

**Files:**
- Create: `docs/og-image.png` (1200×630)

- [ ] **Step 1: Pick the source image**

Use `docs/screenshots/hero-everything.png` as the base. Composite it with the wordmark and tagline overlaid in the bottom-third area (text region).

- [ ] **Step 2: Generate via Pillow**

```python
# Run as a one-off script or inline:
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

ROOT = Path("/home/administrator/Code/geographica")
hero = Image.open(ROOT / "docs/screenshots/hero-everything.png")

# Crop hero to 1200x420 (top portion)
hero_aspect = hero.width / hero.height
target_w = 1200
target_h = 420
# Resize maintaining aspect, then crop to target
scale = target_w / hero.width
new_h = int(hero.height * scale)
hero_resized = hero.resize((target_w, new_h), Image.Resampling.LANCZOS)
hero_crop = hero_resized.crop((0, 0, target_w, target_h))

# Compose final 1200x630
canvas = Image.new("RGB", (1200, 630), "#0d1117")
canvas.paste(hero_crop, (0, 0))

# Wordmark + tagline in the bottom region
draw = ImageDraw.Draw(canvas)
try:
    title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 80)
    tagline_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
except OSError:
    title_font = ImageFont.load_default()
    tagline_font = ImageFont.load_default()

# Favicon top-left of text area
fav = Image.open(ROOT / "docs/geographica_favicon.png").convert("RGBA").resize((100, 100))
canvas.paste(fav, (60, 450), fav)
draw.text((180, 450), "Geographica", font=title_font, fill="#e6edf3")
draw.text((180, 545),
          "Offline-first GIS for the field — built in 19 days with an AI agent team.",
          font=tagline_font, fill="#8b949e")

canvas.save(ROOT / "docs/og-image.png", "PNG", optimize=True)
print("Saved", ROOT / "docs/og-image.png")
```

- [ ] **Step 3: Visually inspect**

Open `docs/og-image.png`. Acceptance: 1200×630, hero image clearly visible in top portion, wordmark + tagline legible at common preview-card sizes (~600×315 on Slack/Twitter).

- [ ] **Step 4: Commit**

```bash
git add docs/og-image.png
git commit -m "$(cat <<'EOF'
docs(og-image): 1200x630 social-share card

Composited from the hero screenshot + favicon + wordmark + tagline.
Configured via repo Settings → Social preview in Task 6.2.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6.2: Configure repo Settings → Social preview

**Files:** none (GitHub UI configuration; not a file change)

- [ ] **Step 1: Upload the OG image**

Cameron (or whoever has admin access to the repo) navigates to:
**Settings → General → Social preview → Edit → Upload an image**
and uploads `docs/og-image.png`.

- [ ] **Step 2: Verify**

Paste the repo URL into a Slack-class preview tool:
- https://www.opengraph.xyz/?url=https://github.com/cameronzucker/geographica
- Or paste into a Slack #scratch channel (then immediately delete the message)

Acceptance: preview shows the custom OG image with wordmark + tagline visible.

- [ ] **Step 3: Document the configuration in implementation log (defer to Task 7.2)** — no commit here.

---

### Task 6.3: Cross-link audit script

**Files:**
- Create: `scripts/audit_doc_links.sh`

- [ ] **Step 1: Write the audit script**

```bash
#!/usr/bin/env bash
# Walk every relative markdown link in the doc set and verify each target exists.
# Exits non-zero if any broken link is found.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DOCS=(
  "README.md"
  "docs/SETUP.md"
  "docs/MANUAL_SETUP.md"
  "docs/PROCESS.md"
  "docs/COST_METHODOLOGY.md"
)

broken=0
for src in "${DOCS[@]}"; do
  if [ ! -f "$src" ]; then
    echo "BROKEN: $src does not exist"
    broken=$((broken + 1))
    continue
  fi
  src_dir="$(dirname "$src")"
  # Extract relative .md, .png, .jpg, .py, .sh, .json, .sql, .ts, .js, .yml links
  grep -oE '\]\(([a-zA-Z0-9_./#-]+)\)' "$src" \
    | sed -E 's/\]\(([^)]+)\)/\1/' \
    | grep -vE '^https?://' \
    | grep -vE '^mailto:' \
    | while read -r link; do
        target="${link%%#*}"
        [ -z "$target" ] && continue
        # Resolve relative to the source file's directory
        if [ "${target:0:1}" = "/" ]; then
          full="$ROOT$target"
        else
          full="$src_dir/$target"
        fi
        # Normalize via realpath (without --relative-to since some installs don't support it)
        if [ ! -e "$full" ]; then
          echo "BROKEN: $src -> $link (resolves to $full)"
          broken=$((broken + 1))
        fi
      done
done

if [ "$broken" -gt 0 ]; then
  echo ""
  echo "Found $broken broken link(s)."
  exit 1
fi
echo "All links resolve."
```

- [ ] **Step 2: Run it**

```bash
cd /home/administrator/Code/geographica && chmod +x scripts/audit_doc_links.sh && ./scripts/audit_doc_links.sh
```

Expected: `All links resolve.` (exit 0).

If broken links are found: fix them and re-run until clean.

- [ ] **Step 3: Commit**

```bash
git add scripts/audit_doc_links.sh
git commit -m "$(cat <<'EOF'
chore(scripts): cross-doc link audit

Walks all .md files in the README + 4 sibling docs, extracts every
relative link, verifies each target exists. Exits non-zero on broken
links so it can be wired into CI later.

Agent: <subagent-moniker>
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6.4: Mermaid render verification

**Files:** none (verification only)

- [ ] **Step 1: Push the current branch (still `dev`) to GitHub**

If commits in this overhaul haven't been pushed yet:

```bash
cd /home/administrator/Code/geographica && git push origin dev
```

(Per CLAUDE.md, plain `git push` to dev is allowed; force-push is banned.)

- [ ] **Step 2: View the README on github.com**

Navigate to `https://github.com/cameronzucker/geographica/blob/dev/README.md`. Acceptance:
- Mermaid block in the Architecture section renders as a flowchart, not as a literal code fence
- Hero screenshot displays correctly
- All inline feature-group screenshots display correctly
- Badge row is visible and not broken
- Favicon image displays at the title

- [ ] **Step 3: If anything renders incorrectly**

For Mermaid issues: GitHub Mermaid support has known edge cases — if a node label uses unescaped characters, it can break the whole diagram. Validate the Mermaid block at https://mermaid.live (paste the diagram source). Fix and recommit.

For image issues: verify the relative path is correct from the README's perspective (`docs/screenshots/...` relative to repo root).

- [ ] **Step 4: No commit if everything renders.** Document in impl log (Task 7.2).

---

# Phase 7 — Final review + ship

Goal: Cameron reads all five docs end-to-end (per Definition of Done §10) and approves. Then commit the impl-log entry that records this overhaul as a completed work item.

---

### Task 7.1: User end-to-end review

**Files:** none (review-only)

- [ ] **Step 1: Hand off to Cameron**

Surface to Cameron a clear "ready for end-to-end review" message with:
- Direct links to all 5 docs in the GitHub UI (so the rendering is what he reviews, not the source)
- Direct link to the OG-image preview check (opengraph.xyz URL)
- Link to the cost-audit script + most recent run output
- A checklist of the Definition of Done items he should personally verify

- [ ] **Step 2: Wait for explicit approval**

Cameron must say "approved" (or equivalent — "looks good, ship it"). Pre-commit speculation does not count.

- [ ] **Step 3: Address any feedback**

If Cameron requests changes, return to the relevant phase/task, make the change, recommit, and re-loop through Step 1.

---

### Task 7.2: Implementation log entry + final clean-up

**Files:**
- Modify: `dev/implementation-log.md` (prepend new entry at top)

- [ ] **Step 1: Compose the impl-log entry**

```markdown
## 2026-04-25 — README overhaul

Refactored the 838-line monolithic README.md into a 5-document set
(README + SETUP + MANUAL_SETUP + PROCESS + COST_METHODOLOGY) plus
supporting assets (audit script, screenshots, custom OG image, Mermaid
architecture diagram, custom badges). Designed to serve four reader
audiences (exec, peer, leadership, user) via progressive disclosure.

**Spec:** `docs/superpowers/specs/2026-04-25-readme-overhaul-design.md`
**Plan:** `docs/superpowers/plans/2026-04-25-readme-overhaul-plan.md`

**What landed:**
- `README.md` rewritten (~210 lines, from 838)
- `docs/SETUP.md` (new, ~150 lines, wizard happy path)
- `docs/MANUAL_SETUP.md` (new, ~500 lines, advanced/recovery/AI-agent reference)
- `docs/PROCESS.md` (new, ~250 lines, AI agent team meta-story)
- `docs/COST_METHODOLOGY.md` (new, ~120 lines, cost audit + reproduction)
- `scripts/audit_inference_cost.py` (productionized cost audit, pytest-tested)
- `scripts/capture_readme_screenshots.py` (Playwright-driven shot capture)
- `scripts/postprocess_screenshots.py` (Pillow border + shadow + phone-frame)
- `scripts/audit_doc_links.sh` (cross-link audit)
- 9 PNG screenshots (1 hero + 5 inline + 3 gallery), all framed
- `docs/og-image.png` (1200x630 social-share card)

**Voice rule held:** declarative, no first-person, across all 5 docs.

**Cost methodology:** README headline is ~$2,500 (uncached I/O at API
rates, matches ccusage). Full $21.8K list price (with cache reads at
list rate) disclosed in COST_METHODOLOGY.md with reproduction script.

**Verified:** Cameron read all 5 docs end-to-end and approved on
2026-04-25 (or actual date if later).

Total commits this overhaul: ~30. Agent: tinaja (controller) + per-task
subagents.
```

- [ ] **Step 2: Verify final doc-set state**

```bash
cd /home/administrator/Code/geographica
echo "=== Doc line counts ==="
wc -l README.md docs/SETUP.md docs/MANUAL_SETUP.md docs/PROCESS.md docs/COST_METHODOLOGY.md

echo "=== Voice check across all 5 docs ==="
for f in README.md docs/SETUP.md docs/MANUAL_SETUP.md docs/PROCESS.md docs/COST_METHODOLOGY.md; do
  matches=$(grep -cE "\\b(I|I'm|I've|I'll|me|my|mine|we|we're|we've|we'll|us|our|ours)\\b" "$f" || echo "0")
  echo "$f: $matches first-person matches"
done

echo "=== Link audit ==="
./scripts/audit_doc_links.sh

echo "=== Screenshot inventory ==="
ls -la docs/screenshots/*.png docs/screenshots/gallery/*.png docs/og-image.png 2>/dev/null
```

Acceptance:
- All 5 docs in their target line-count range
- All 5 docs show 0 first-person matches
- Link audit reports all links resolve
- All 9 screenshots + OG image exist as files

- [ ] **Step 3: Commit the impl-log entry**

```bash
git add dev/implementation-log.md
git commit -m "$(cat <<'EOF'
docs(log): 2026-04-25 README overhaul shipped

Multi-doc README refactor complete: 5-doc set (README + SETUP +
MANUAL_SETUP + PROCESS + COST_METHODOLOGY) + 4 scripts + 9 screenshots
+ OG image. ~30 commits across 7 phases. Voice rule held throughout.
Cameron approved end-to-end review.

Agent: tinaja
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 4: Push to remote**

```bash
cd /home/administrator/Code/geographica && git push origin dev
```

- [ ] **Step 5: Optional — open a PR for `dev → main` if Cameron wants to ship to main**

Defer to Cameron. The merge to main is what triggers a release-please version bump (per CLAUDE.md), and the contents of this overhaul are `docs:` only — so no version bump fires automatically. Cameron may want to merge for the cleaner main-branch state, or leave on dev pending other work.

---

## Self-review (post-write)

After writing this plan, the controller agent should run this checklist (one-time, not per-task):

**Spec coverage:** Walk spec §1-§11. For each requirement, confirm a task implements it. Specifically:
- §4.1 Artifact-first hero treatment → README skeleton (T1.1) + content (T4.1, T4.4)
- §4.2 Cost framing in callout → T4.4
- §4.3 Two-number cost methodology → T0.1-T0.3 + T2.1
- §4.4 Voice rule → enforced via grep step in every doc-writing task
- §4.5 Screenshot tier list → T5.1-T5.10
- §4.6 5-doc split → T1.1, T1.2-T1.4, T2.1, T3.1-T3.7
- §4.7 Visual identity → T4.2 (Mermaid), T4.3 (favicon + badges), T5.8-T5.9 (framing), T6.1-T6.2 (OG)
- §4.8 Mixed capture method → T5.2-T5.6 (Playwright) + T5.7 (manual)
- §5 README outline → T1.1 + T4.1-T4.4 + T5.10
- §6 Sibling docs → T1.2-T1.4, T2.1, T3.1-T3.7
- §7 Asset deliverables → T0.2 (audit), T5.1 (capture), T5.8-T5.9 (post), T6.1 (OG), T6.3 (link audit)
- §8 Out of scope → confirmed: no task touches CHANGELOG.md, CONTRIBUTING.md, etc.
- §9 Open questions / risks → T5.7 (manual capture for screenshots that Playwright can't produce); T2.1 (two-number framing); T1.2-T1.3 (verbatim lift, no rewrite); T3.1-T3.7 (worked-example anchors PROCESS.md; voice rule enforced)
- §10 Definition of done → T7.1 (user review) + T7.2 (verification block in impl-log entry)
- §11 Sequencing → mirrored in this plan's phase ordering

**Placeholder scan:** Walk every `[N from Step 1]`, `<subagent-moniker>`, `<shot-name>` token. Confirm they're contextually-clear placeholders (filled in at execution time, not unspecified intent). All such tokens in this plan are intentional.

**Type/path consistency:** Function names used across tasks (`aggregate_directory`, `price_totals`, `desktop_frame`, `phone_frame`, `shot_3d_terrain`, etc.) are defined exactly once and referenced consistently.
