"""Render a findings list + run metadata into a markdown report.

Format pinned in docs/superpowers/specs/2026-04-20-exploratory-agent-harness-design.md.
The format is load-bearing for the human-review workflow; only add
optional fields, never rearrange.
"""
from __future__ import annotations


def render_markdown(findings: list, meta: dict) -> str:
    lines: list[str] = []
    started = meta.get("started_at", "?")
    ended = meta.get("ended_at", "?")
    lines.append(f"# Exploratory-Agent Findings — {started}")
    lines.append("")
    lines.append(f"**Container:** {meta.get('container_image', '?')}")
    lines.append(f"**Pre-state:** {meta.get('pre_state', '?')}")
    lines.append(f"**Agent model:** {meta.get('model', '?')}")
    lines.append(f"**Runtime:** {started} to {ended}")
    lines.append(f"**Turns used:** {meta.get('turns_used', 0)} / {meta.get('turns_cap', 0)}")
    lines.append(f"**Transcript:** {meta.get('transcript_path', '?')}")
    lines.append(f"**Stop reason:** {meta.get('stop_reason', '?')}")
    lines.append(f"**Findings:** {len(findings)}")
    lines.append("")
    lines.append("---")
    lines.append("")
    for i, f in enumerate(findings, start=1):
        sev = (f.get("severity") or "unknown").upper()
        classi = f.get("classification", "novel")
        lines.append(f"## Finding {i} — {sev} — {classi}")
        lines.append("")
        lines.append(f"**ID:** `{f['id']}`")
        lines.append(f"**Title:** {f.get('title', '')}")
        lines.append("")
        lines.append("**Reproduction:**")
        for step in f.get("reproduction_steps", []):
            lines.append(f"- {step}")
        lines.append("")
        lines.append(f"**Input:** `{f.get('input')}`")
        lines.append("")
        lines.append(f"**Observed:** {f.get('observed', '')}")
        lines.append("")
        lines.append(f"**Expected:** {f.get('expected', '')}")
        lines.append("")
        lines.append("**Evidence:**")
        for k, v in (f.get("evidence") or {}).items():
            lines.append(f"- {k}: `{v}`")
        lines.append("")
        lines.append("---")
        lines.append("")
    return "\n".join(lines)
