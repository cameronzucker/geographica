"""Anthropic SDK tool-use message loop.

Runs one exploratory session. Iterates: send conversation to Claude,
receive a response, dispatch any tool_use blocks to their registered
handlers, append tool_result blocks back into the conversation, repeat
until the model signals stop OR max_turns elapsed OR deadline passed
OR token cap hit.

Design:
- System prompt is prompt-cached (ephemeral) so per-turn cost stays low
  for ~5 minutes (Anthropic ephemeral cache TTL).
- Tool outputs are JSON-serialized as content strings (Anthropic
  tool_result expects a string or list-of-blocks).
- Tool handlers MUST NOT raise; any exception is caught and reported
  to the model as `{"error": str(e)}`. The full traceback is logged
  to the transcript (not sent to the model) per adversarial-review
  SHOULD-FIX 2.4.
- Per-run token cap (MUST-FIX 2.1) breaks the loop when cumulative
  input or output tokens exceed configurable thresholds. Default
  2M input + 200k output caps cost at roughly $10 worst-case.
- Input schema validation (MUST-FIX 1.2): every tool_use block's
  `input` is validated against its registered JSON schema before
  dispatch; validation errors flow back to the model as tool_results
  with `{"ok": false, "error": "schema violation: ..."}`.
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Optional

import jsonschema


@dataclass
class SessionContext:
    client: Any                       # anthropic.Anthropic
    system_prompt: str
    browser: Any                      # BrowserTools or None
    api: Any                          # ApiTools or None
    container: Any                    # ContainerTools or None
    control: Any                      # ControlTools or None
    reporting: Any                    # ReportingTools
    transcript: Any                   # TranscriptWriter
    max_turns: int = 200
    deadline_epoch: float = 0.0
    model: str = "claude-sonnet-4-6"
    messages: list[dict] = field(default_factory=list)
    # MUST-FIX 2.1: token budget
    cumulative_input_tokens: int = 0
    cumulative_output_tokens: int = 0
    max_input_tokens: int = 2_000_000
    max_output_tokens: int = 200_000


def _validate_input(name: str, inp: Any, schema: dict) -> Optional[str]:
    """Return None if valid, else a short error string."""
    if not isinstance(inp, dict):
        return f"input must be an object, got {type(inp).__name__}"
    try:
        jsonschema.validate(inp, schema.get("input_schema", {}))
    except jsonschema.ValidationError as e:
        return f"schema violation: {e.message}"
    return None


def run_session(ctx: SessionContext) -> None:
    from .tools import TOOL_REGISTRY
    from . import schema as _schema

    ctx.messages.append({"role": "user", "content": "Begin your exploratory session."})

    for turn in range(ctx.max_turns):
        if ctx.deadline_epoch and time.time() >= ctx.deadline_epoch:
            ctx.transcript.log({"event": "deadline_hit", "turn": turn})
            break

        # MUST-FIX 2.1: check token caps BEFORE making the API call
        if ctx.cumulative_input_tokens > ctx.max_input_tokens:
            ctx.transcript.log({
                "event": "token_cap_hit", "turn": turn,
                "kind": "input",
                "cumulative_input_tokens": ctx.cumulative_input_tokens,
                "max_input_tokens": ctx.max_input_tokens,
            })
            break
        if ctx.cumulative_output_tokens > ctx.max_output_tokens:
            ctx.transcript.log({
                "event": "token_cap_hit", "turn": turn,
                "kind": "output",
                "cumulative_output_tokens": ctx.cumulative_output_tokens,
                "max_output_tokens": ctx.max_output_tokens,
            })
            break

        system_block = [{
            "type": "text",
            "text": ctx.system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]
        resp = ctx.client.messages.create(
            model=ctx.model,
            max_tokens=4096,
            system=system_block,
            tools=_schema.TOOL_SCHEMAS,
            messages=ctx.messages,
        )
        # Accumulate usage BEFORE processing, so a cap-hit still records.
        in_tok = getattr(getattr(resp, "usage", None), "input_tokens", 0) or 0
        out_tok = getattr(getattr(resp, "usage", None), "output_tokens", 0) or 0
        ctx.cumulative_input_tokens += int(in_tok)
        ctx.cumulative_output_tokens += int(out_tok)

        ctx.transcript.log({
            "event": "turn", "turn": turn,
            "stop_reason": getattr(resp, "stop_reason", None),
            "usage": {"input": int(in_tok), "output": int(out_tok),
                       "cumulative_input": ctx.cumulative_input_tokens,
                       "cumulative_output": ctx.cumulative_output_tokens},
        })

        assistant_blocks: list[dict] = []
        tool_results: list[dict] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
                ctx.transcript.log({"event": "assistant_text",
                                     "text": block.text[:500]})
            elif btype == "tool_use":
                assistant_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                ctx.transcript.log({
                    "event": "tool_call", "name": block.name, "id": block.id,
                    "args": block.input,
                })
                entry = TOOL_REGISTRY.get(block.name)
                if entry is None:
                    result = {"ok": False, "error": f"unknown tool: {block.name}"}
                else:
                    factory, tool_schema = entry
                    # MUST-FIX 1.2: validate input against schema before dispatch
                    validation_err = _validate_input(block.name, block.input, tool_schema)
                    if validation_err is not None:
                        result = {"ok": False, "error": validation_err}
                        ctx.transcript.log({
                            "event": "schema_violation",
                            "name": block.name, "id": block.id,
                            "error": validation_err,
                        })
                    else:
                        try:
                            handler = factory(ctx)
                            if isinstance(block.input, dict):
                                result = handler(**block.input)
                            else:
                                result = handler(block.input)
                        except Exception as e:  # noqa: BLE001
                            result = {"ok": False,
                                       "error": f"{type(e).__name__}: {e}"}
                            # SHOULD-FIX 2.4: log full traceback to transcript
                            ctx.transcript.log({
                                "event": "tool_error",
                                "tool_name": block.name,
                                "id": block.id,
                                "traceback": traceback.format_exc(),
                            })
                ctx.transcript.log({"event": "tool_result",
                                     "id": block.id, "result": result})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str, ensure_ascii=False),
                })
        ctx.messages.append({"role": "assistant", "content": assistant_blocks})

        if getattr(ctx.reporting, "stop_reason", None) is not None:
            ctx.transcript.log({"event": "stop_signalled",
                                 "reason": ctx.reporting.stop_reason})
            break

        if tool_results:
            ctx.messages.append({"role": "user", "content": tool_results})
        else:
            ctx.messages.append({
                "role": "user",
                "content": "Continue. What hypothesis will you test next?",
            })
