"""Reporting tools: report_finding, checkpoint, stop.

ReportingTools accumulates findings in memory during the session; the
agent_loop writes them to disk at session end via findings_writer.

MUST-FIX 4.2: report_finding_sync dedupes on a coarse hash of
(classification, normalized_title, sorted(input.keys())). On collision
the existing finding ID is returned with {"deduped": True}.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Optional

from . import register


def _hash_key(classification: str, title: str, input_keys: list[str]) -> str:
    norm_title = re.sub(r"\W+", " ", (title or "").lower()).strip()
    key = f"{classification}|{norm_title}|{sorted(input_keys)}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


class ReportingTools:
    def __init__(self, findings_dir: str) -> None:
        self.findings_dir = Path(findings_dir)
        self.findings_dir.mkdir(parents=True, exist_ok=True)
        self.findings: list[dict] = []
        self.checkpoints: list[str] = []
        self.stop_reason: Optional[str] = None
        self._hashes: dict[str, str] = {}

    def report_finding_sync(
        self, *,
        classification: str,
        severity: str,
        title: str,
        reproduction_steps: list,
        input: dict,
        observed: str,
        expected: str,
        evidence: dict,
    ) -> dict:
        h = _hash_key(classification, title, list((input or {}).keys()))
        if h in self._hashes:
            return {"id": self._hashes[h], "deduped": True}

        fid = f"F-{len(self.findings) + 1:03d}"
        self._hashes[h] = fid
        self.findings.append({
            "id": fid,
            "classification": classification,
            "severity": severity,
            "title": title,
            "reproduction_steps": list(reproduction_steps),
            "input": dict(input),
            "observed": observed,
            "expected": expected,
            "evidence": dict(evidence),
        })
        return {"id": fid}

    def checkpoint_sync(self, message: str) -> dict:
        self.checkpoints.append(message)
        return {"ok": True}

    def stop_sync(self, reason: str) -> dict:
        self.stop_reason = reason
        return {"stopped": True}


_SCHEMAS: list[dict] = [
    {
        "name": "report_finding",
        "description": (
            "Log a bug or suspicious observation for human review. "
            "Required: classification (one of the seeded classes or "
            "\"novel\"), severity, title, reproduction_steps, input, "
            "observed, expected, evidence (paths to screenshots/etc.)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "classification": {"type": "string"},
                "severity": {"type": "string", "enum": ["critical", "high", "medium", "low", "cosmetic"]},
                "title": {"type": "string"},
                "reproduction_steps": {"type": "array", "items": {"type": "string"}},
                "input": {"type": "object"},
                "observed": {"type": "string"},
                "expected": {"type": "string"},
                "evidence": {"type": "object"},
            },
            "required": ["classification", "severity", "title", "reproduction_steps",
                         "input", "observed", "expected", "evidence"],
        },
    },
    {
        "name": "checkpoint",
        "description": "Log a progress marker to the transcript (not a finding).",
        "input_schema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    },
    {
        "name": "stop",
        "description": "Signal the agent is done exploring. The loop exits after this turn.",
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
        },
    },
]


def _factory_report(ctx):
    return ctx.reporting.report_finding_sync


def _factory_checkpoint(ctx):
    return ctx.reporting.checkpoint_sync


def _factory_stop(ctx):
    return ctx.reporting.stop_sync


register("report_finding", _factory_report, _SCHEMAS[0])
register("checkpoint", _factory_checkpoint, _SCHEMAS[1])
register("stop", _factory_stop, _SCHEMAS[2])

from .. import schema as _schema_mod
_schema_mod.TOOL_SCHEMAS.extend(_SCHEMAS)
