"""JSON schemas for every tool the agent can call.

Each entry in TOOL_SCHEMAS is an Anthropic tool-use dict:
  { "name": str, "description": str, "input_schema": {...} }

These are sent verbatim to the Messages API in the `tools` parameter.

The handlers live in `dev/harness/exploratory_agent/tools/`. The registry
that maps name -> handler lives in `dev/harness/exploratory_agent/tools/__init__.py`.
The two are kept in sync by the unit test `test_schema_registry_parity`.
"""
from __future__ import annotations

TOOL_SCHEMAS: list[dict] = []

# Populated by later tasks; each tools/*.py task appends its schemas here.
