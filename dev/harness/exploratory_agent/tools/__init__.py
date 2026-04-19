"""Tool registry. Maps tool name -> (handler factory, schema).

Every `tools/*.py` module calls `register(name, handler_factory, schema_dict)`
at import time so the agent loop can dispatch by name.

`handler_factory(context)` returns a callable that the loop invokes with
the tool_use input dict. Context is a SessionContext (agent_loop.py) holding
the Playwright page, the LXD container name, the findings writer, etc.
"""
from __future__ import annotations

from typing import Callable

TOOL_REGISTRY: dict[str, tuple[Callable, dict]] = {}


def register(name: str, factory: Callable, schema: dict) -> None:
    if name in TOOL_REGISTRY:
        raise ValueError(f"tool {name!r} already registered")
    TOOL_REGISTRY[name] = (factory, schema)


# Import every tools/*.py module so each one can call register() at import time.
# Order doesn't matter but the side effect is required.
from . import browser  # noqa: F401,E402
from . import api  # noqa: F401,E402
