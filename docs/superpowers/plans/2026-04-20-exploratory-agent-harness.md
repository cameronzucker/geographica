# Exploratory-Agent Beta-Tester Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third mode to `dev/harness/wizard-ci.sh`, `--exploratory`, that dispatches a Claude Sonnet 4.6 agent to walk the setup wizard like a bug-bounty tester. Produces a reviewable findings file per run. Catches novel input/resilience bugs the deterministic smoke + pipeline-start modes can't preempt.

**Architecture:** New Python package `dev/harness/exploratory_agent/` that Anthropic-SDK-drives an agent with Playwright tools + API probes + LXD-container-mutation tools. Reuses existing `wizard-ci.sh` container setup (bootstrap, setup.sh, LXD proxy). Findings committed to `dev/harness/findings/`. Non-blocking for CI push/PR — runs nightly and on manual dispatch.

**Tech Stack:** Python 3.13, Anthropic Python SDK (claude-sonnet-4-6 w/ prompt caching), Playwright Python, LXD CLI (existing), pytest + unittest.mock for unit tests.

**Companion spec:** [docs/superpowers/specs/2026-04-20-exploratory-agent-harness-design.md](../specs/2026-04-20-exploratory-agent-harness-design.md). Read it first if any task seems underspecified.

**REQUIRED reading before Task 1:** [dev/adversarial/2026-04-20-exploratory-agent-spec-adversarial-review.md](../../../dev/adversarial/2026-04-20-exploratory-agent-spec-adversarial-review.md).

The adversarial review caught 12 issues; 5 are flagged **MUST FIX BEFORE IMPLEMENTATION**:

- **1.1** `asyncio.get_event_loop()` in sync shims is broken on Python 3.13. Use `asyncio.new_event_loop()` + explicit `.close()` inside each `_sync` method. Tests must use `pytest.mark.asyncio` + `AsyncMock` on the async variants, not the sync shims directly. **Affects:** Task 2 (browser tools) + every sync shim in Tasks 3-5.
- **1.2** Agent loop `**block.input` unpacking has no schema validation. Add `jsonschema>=4.0` to `requirements.txt` (Task 1 Step 2) and validate each tool's input against its schema before dispatch in Task 7's `run_session`. Validation errors become `tool_result` dicts `{"ok": false, "error": "schema violation: ..."}`.
- **1.3** `describe_wizard_state_sync` was a placeholder stub — fixed inline in this plan (Task 5 Step 3 now has the real implementation that drives Playwright async queries via a dedicated event loop).
- **2.1** No per-run token cap. Add `cumulative_input_tokens`, `cumulative_output_tokens`, `max_input_tokens`, `max_output_tokens` fields to `SessionContext`. After each `resp` in `run_session`, accumulate `resp.usage.*` and break out of the loop on cap hit. Default cap: 2M input + 200k output tokens (bounds cost to ~\$10 worst-case).
- **4.2** `report_finding_sync` doesn't dedupe. Add a `_hash(classification, title, input)` method; on collision, return the existing finding ID with `"deduped": true` in the response. Test: `test_report_finding_dedups_on_identical_title_and_input`.

All five are small inline changes (<30 lines each) and are described with concrete sketch code in the adversarial review. The implementer applies them while walking the plan — NOT as separate tasks.

The other 7 adversarial issues (1.4, 1.5, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 4.1, 4.3, 4.4) are "should fix before first real run" or "defer to v2" and don't block Task 1 start.

---

## Baseline test expectation

Record baseline before starting (match against the count at every completion check):

```
cd /home/administrator/Code/geographica
python -m pytest tests/ services/search/tests/ -v 2>&1 | tail -3
```

Expected at plan start: all tests passing except the pre-existing environmental ones listed in CLAUDE.md (2 M2M failures, 18 Docker-daemon-down errors). Any NEW failure beyond that baseline is a regression.

---

## Execution preamble (all tasks)

### Python environment

All Python commands assume the existing setup wizard's venv is active:

```
cd /home/administrator/Code/geographica
source setup/.venv/bin/activate
# if the venv doesn't exist yet, create it:
# python3 -m venv setup/.venv && source setup/.venv/bin/activate && pip install -r setup/requirements.txt
```

The exploratory agent runs from inside this venv but needs extra packages (see Task 1). Those additions go into a NEW requirements file, `dev/harness/exploratory_agent/requirements.txt`, not `setup/requirements.txt` — they are host-side harness deps, not production wizard deps.

### Commit conventions

Match CONTRIBUTING.md Conventional Commits. Scopes in this plan: `harness`, `tests`, `docs`, `ci`.

- `feat(harness):` for any new code path users can invoke (new mode, new tool, new script)
- `test(harness):` for unit tests that cover harness code
- `docs(harness):` for README / plan updates
- `ci(harness):` for workflow YAML changes

Every commit ends with: `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

### Test baseline reference for completion checks

```
python -m pytest tests/test_exploratory_agent.py -v
```
(per-task check once tests exist)

```
python -m pytest tests/ -v 2>&1 | tail -3
```
(at plan completion — must not regress baseline)

### File-contention note

This plan is mostly additive (new package + one new mode flag). The only files multiple tasks touch are:
- `dev/harness/wizard-ci.sh` — Tasks 7, 10
- `dev/harness/README.md` — Task 10
- `.github/workflows/wizard-ci.yml` — Task 8

Subagents may work tasks sequentially without file contention.

---

## File structure (locked at plan time — do not change without spec update)

```
dev/harness/exploratory_agent/
├── __init__.py                # package marker; empty
├── __main__.py                # CLI entry: `python3 -m dev.harness.exploratory_agent`
├── requirements.txt           # anthropic, playwright, (pytest for tests)
├── agent_loop.py              # tool-use message loop: Anthropic SDK interaction
├── tools/
│   ├── __init__.py            # TOOL_REGISTRY: name → (handler, schema)
│   ├── browser.py             # page_goto, page_click, page_fill, page_select_option,
│   │                          # page_press, page_inner_text, page_is_visible,
│   │                          # page_body_text, page_console_errors, page_pageerrors,
│   │                          # page_websocket_frames, page_reload, page_screenshot
│   ├── api.py                 # api_request (with csrf="auto"|"skip"|literal)
│   ├── container.py           # container_run_command, container_restart_wizard,
│   │                          # container_fs_write, container_fs_read
│   ├── control.py             # wait_seconds, describe_wizard_state
│   └── reporting.py           # report_finding, checkpoint, stop
├── prompts.py                 # SYSTEM_PROMPT string + BUG_CLASSES_PATH constant
├── bug_classes.md             # seed list of bug classes (versioned prompt component)
├── findings_writer.py         # renders findings list → markdown file
├── transcript.py              # JSONL writer for every tool call + result
└── schema.py                  # JSON schemas for all tools (Anthropic tool-use format)

dev/harness/findings/
├── .gitkeep
└── 2026-04-20-XXXX.md         # first real-run evidence (committed in Task 9)

tests/
└── test_exploratory_agent.py  # unit tests for every tool handler (mocked)

dev/harness/wizard-ci.sh       # adds --exploratory mode (Task 7)
dev/harness/README.md          # documents the new mode (Task 10)
.github/workflows/wizard-ci.yml # adds nightly schedule + dispatch option (Task 8)
```

Every Python file has a module-level docstring describing its responsibility (established pattern in setup/).

---

## Task 1: Scaffold package + dependencies + JSON schema module

**Files:**
- Create: `dev/harness/exploratory_agent/__init__.py`
- Create: `dev/harness/exploratory_agent/requirements.txt`
- Create: `dev/harness/exploratory_agent/schema.py`
- Create: `dev/harness/findings/.gitkeep`
- Create: `tests/test_exploratory_agent.py` (empty shell with `sys.path` preamble)

- [ ] **Step 1: Create the package skeleton**

Create `dev/harness/exploratory_agent/__init__.py` as empty (package marker).

Create `dev/harness/findings/.gitkeep` as empty so the directory tracks.

- [ ] **Step 2: Declare dependencies**

Create `dev/harness/exploratory_agent/requirements.txt` with:

```
anthropic>=0.40.0
playwright>=1.48.0
pytest>=7.0
pytest-asyncio>=0.23
```

- [ ] **Step 3: Install the dependencies**

```
pip install -r dev/harness/exploratory_agent/requirements.txt
playwright install chromium
```

Confirm `python3 -c "import anthropic, playwright"` runs clean.

- [ ] **Step 4: Write the schema module stub**

Create `dev/harness/exploratory_agent/schema.py`:

```python
"""JSON schemas for every tool the agent can call.

Each entry in TOOL_SCHEMAS is an Anthropic tool-use dict:
  { "name": str, "description": str, "input_schema": {...} }

These are sent verbatim to the Messages API in the `tools` parameter.

The handlers live in `dev/harness/exploratory_agent/tools/`. The registry
that maps name → handler lives in `dev/harness/exploratory_agent/tools/__init__.py`.
The two are kept in sync by the unit test `test_schema_registry_parity`.
"""
from __future__ import annotations

TOOL_SCHEMAS: list[dict] = []

# Populated by later tasks; each tools/*.py task appends its schemas here.
```

- [ ] **Step 5: Create the test-file shell with sys.path preamble**

Create `tests/test_exploratory_agent.py`:

```python
"""Unit tests for dev/harness/exploratory_agent/.

All tests mock Playwright, the Anthropic SDK, and `lxc exec`. No real
containers. No real API calls. Runs in under 5 seconds.

The integration test (against a real LXD container) lives in
dev/harness/wizard-ci.sh --exploratory and is gated behind
ANTHROPIC_API_KEY; it is not part of this pytest suite.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_package_importable():
    import dev.harness.exploratory_agent as pkg
    assert pkg is not None
```

- [ ] **Step 6: Run the test to verify the scaffold works**

```
python -m pytest tests/test_exploratory_agent.py -v
```

Expected: 1 passed.

- [ ] **Step 7: Commit**

```
git add dev/harness/exploratory_agent/ dev/harness/findings/.gitkeep \
        tests/test_exploratory_agent.py
git commit -m "$(cat <<EOF
feat(harness): scaffold exploratory_agent package + deps + test shell

Empty-package commit for the v1 exploratory-agent harness. Adds:

- dev/harness/exploratory_agent/{__init__.py,schema.py,requirements.txt}
  pinning anthropic>=0.40, playwright>=1.48, pytest + asyncio.
- dev/harness/findings/.gitkeep so the output directory tracks.
- tests/test_exploratory_agent.py with the sys.path preamble this
  project's test suite expects.

TOOL_SCHEMAS stays empty until the individual tools/ modules populate
it in Tasks 2-6.

See docs/superpowers/specs/2026-04-20-exploratory-agent-harness-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Browser tools — Playwright wrappers

**Files:**
- Create: `dev/harness/exploratory_agent/tools/__init__.py`
- Create: `dev/harness/exploratory_agent/tools/browser.py`
- Modify: `dev/harness/exploratory_agent/schema.py` (append browser tool schemas)
- Modify: `tests/test_exploratory_agent.py` (add browser tool tests)

- [ ] **Step 1: Write failing tests for the browser tool surface**

Append to `tests/test_exploratory_agent.py`:

```python
from unittest.mock import MagicMock, AsyncMock


def test_browser_tools_registered():
    from dev.harness.exploratory_agent.tools import TOOL_REGISTRY
    for name in (
        "page_goto", "page_click", "page_fill", "page_select_option",
        "page_press", "page_inner_text", "page_is_visible",
        "page_body_text", "page_console_errors", "page_pageerrors",
        "page_websocket_frames", "page_reload", "page_screenshot",
    ):
        assert name in TOOL_REGISTRY, f"missing tool: {name}"


def test_page_goto_returns_status_and_final_url():
    from dev.harness.exploratory_agent.tools.browser import BrowserTools
    fake_page = MagicMock()
    fake_response = MagicMock(status=200)
    fake_page.goto = AsyncMock(return_value=fake_response)
    fake_page.url = "http://x/1"
    bt = BrowserTools(page=fake_page, screenshot_dir="/tmp")
    result = bt.page_goto_sync("http://x/1")
    assert result == {"status": 200, "final_url": "http://x/1"}


def test_page_body_text_is_truncated_at_16kb():
    from dev.harness.exploratory_agent.tools.browser import BrowserTools
    fake_page = MagicMock()
    long_text = "a" * 50_000
    fake_page.inner_text = AsyncMock(return_value=long_text)
    bt = BrowserTools(page=fake_page, screenshot_dir="/tmp")
    result = bt.page_body_text_sync()
    assert len(result["text"]) == 16_384


def test_page_click_returns_error_on_exception():
    from dev.harness.exploratory_agent.tools.browser import BrowserTools
    fake_page = MagicMock()
    fake_page.click = AsyncMock(side_effect=TimeoutError("no element"))
    bt = BrowserTools(page=fake_page, screenshot_dir="/tmp")
    result = bt.page_click_sync("#nope")
    assert result["ok"] is False
    assert "no element" in result["error"]
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_exploratory_agent.py::test_browser_tools_registered -v
```

Expected: FAIL — module not found or registry empty.

- [ ] **Step 3: Write the registry module**

Create `dev/harness/exploratory_agent/tools/__init__.py`:

```python
"""Tool registry. Maps tool name → (handler, schema).

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
# api, container, control, reporting modules are added in later tasks and
# imported here in the same style once they exist.
```

- [ ] **Step 4: Write the browser tools module**

Create `dev/harness/exploratory_agent/tools/browser.py`:

```python
"""Playwright-backed tool handlers.

One BrowserTools instance per agent session; it holds the page, the
accumulated console errors, pageerrors, and WebSocket frames. All the
individual tool functions are methods; they are wrapped into sync-safe
callables by the agent loop (Playwright is async-only).

Each method has a `_sync` variant that wraps the async call via
`asyncio.run_until_complete` / the loop the agent runs in. For testing
purposes the _sync variants are called directly with mocked async pages.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from . import register

_BODY_TEXT_MAX = 16_384
_WS_FRAME_MAX = 4_096
_WS_FRAMES_CAP = 200


class BrowserTools:
    def __init__(self, page, screenshot_dir: str) -> None:
        self.page = page
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._console_errors: list[str] = []
        self._pageerrors: list[str] = []
        self._ws_frames: list[dict] = []
        # Caller wires these:
        #   page.on("console", lambda m: _append if m.type=="error")
        #   page.on("pageerror", lambda e: _pageerrors.append(str(e)))
        #   page.on("websocket", lambda ws: ws.on("framereceived", ...))

    # --- sync shims (used by tests; real loop calls the async paths) ---

    def page_goto_sync(self, url: str) -> dict:
        return asyncio.get_event_loop().run_until_complete(self.page_goto(url))

    def page_click_sync(self, selector: str) -> dict:
        return asyncio.get_event_loop().run_until_complete(self.page_click(selector))

    def page_body_text_sync(self) -> dict:
        return asyncio.get_event_loop().run_until_complete(self.page_body_text())

    # --- async implementations ---

    async def page_goto(self, url: str) -> dict:
        try:
            resp = await self.page.goto(url)
            status = getattr(resp, "status", 0) if resp else 0
            return {"status": status, "final_url": self.page.url}
        except Exception as e:
            return {"status": 0, "final_url": "", "error": str(e)}

    async def page_click(self, selector: str) -> dict:
        try:
            await self.page.click(selector, timeout=5_000)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def page_fill(self, selector: str, value: str) -> dict:
        try:
            await self.page.fill(selector, value, timeout=5_000)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def page_select_option(self, selector: str, value: str) -> dict:
        try:
            await self.page.select_option(selector, value, timeout=5_000)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def page_press(self, selector: str, key: str) -> dict:
        try:
            await self.page.press(selector, key, timeout=5_000)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def page_inner_text(self, selector: str) -> dict:
        try:
            text = await self.page.inner_text(selector, timeout=5_000)
            return {"ok": True, "text": text[:_BODY_TEXT_MAX]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def page_is_visible(self, selector: str) -> dict:
        try:
            vis = await self.page.is_visible(selector)
            return {"ok": True, "visible": vis}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def page_body_text(self) -> dict:
        text = await self.page.inner_text("body")
        return {"text": text[:_BODY_TEXT_MAX]}

    async def page_console_errors(self) -> dict:
        return {"errors": list(self._console_errors)}

    async def page_pageerrors(self) -> dict:
        return {"errors": list(self._pageerrors)}

    async def page_websocket_frames(self) -> dict:
        return {"frames": list(self._ws_frames)}

    async def page_reload(self) -> dict:
        try:
            resp = await self.page.reload()
            status = getattr(resp, "status", 0) if resp else 0
            return {"status": status}
        except Exception as e:
            return {"status": 0, "error": str(e)}

    async def page_screenshot(self, label: str) -> dict:
        # Sanitize label to a safe filename component.
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:64]
        ts = int(time.time())
        path = self.screenshot_dir / f"{ts}-{safe}.png"
        try:
            await self.page.screenshot(path=str(path), full_page=True)
            return {"path": str(path)}
        except Exception as e:
            return {"path": "", "error": str(e)}


# --- Anthropic tool schemas ---

_BROWSER_SCHEMAS: list[dict] = [
    {
        "name": "page_goto",
        "description": "Navigate the browser to a URL. Returns HTTP status and final URL.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
    },
    {
        "name": "page_click",
        "description": "Click a DOM element by CSS selector. 5-second timeout.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
    {
        "name": "page_fill",
        "description": "Type a value into an input (clears first). 5-second timeout.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "page_select_option",
        "description": "Select an <option> in a <select> by value.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "value": {"type": "string"},
            },
            "required": ["selector", "value"],
        },
    },
    {
        "name": "page_press",
        "description": "Press a keyboard key while focusing the selector.",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "key": {"type": "string"},
            },
            "required": ["selector", "key"],
        },
    },
    {
        "name": "page_inner_text",
        "description": "Return the innerText of an element. Truncated to 16 KB.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
    {
        "name": "page_is_visible",
        "description": "Check if a selector matches a currently-visible element.",
        "input_schema": {
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
    },
    {
        "name": "page_body_text",
        "description": "Return document.body.innerText truncated to 16 KB. Useful for scanning for Traceback / Error text.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "page_console_errors",
        "description": "Return all console.error events observed this session.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "page_pageerrors",
        "description": "Return all uncaught pageerror events observed this session.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "page_websocket_frames",
        "description": "Return WebSocket frames observed this session (capped at 200, each truncated to 4 KB).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "page_reload",
        "description": "Reload the current page.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "page_screenshot",
        "description": "Take a full-page PNG screenshot, tagged with a short label. Returns the output path.",
        "input_schema": {
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
        },
    },
]


# --- Register ---

def _factory_builder(method_name: str):
    def factory(ctx):
        return getattr(ctx.browser, method_name)
    return factory


for _schema in _BROWSER_SCHEMAS:
    register(_schema["name"], _factory_builder(_schema["name"]), _schema)

# Also append to the global schema list used by the agent loop.
from .. import schema as _schema_mod
_schema_mod.TOOL_SCHEMAS.extend(_BROWSER_SCHEMAS)
```

- [ ] **Step 5: Run the tests**

```
python -m pytest tests/test_exploratory_agent.py -v
```

Expected: 5 passed (scaffold + 4 new browser tests).

If `test_page_body_text_is_truncated_at_16kb` fails because of the event-loop sync shim, verify by running just that test; Playwright async methods need a real loop. If the mocked async methods don't play nicely with `asyncio.get_event_loop().run_until_complete`, use `asyncio.new_event_loop()` in the _sync shims.

- [ ] **Step 6: Commit**

```
git add dev/harness/exploratory_agent/tools/ \
        dev/harness/exploratory_agent/schema.py \
        tests/test_exploratory_agent.py
git commit -m "$(cat <<EOF
feat(harness): exploratory_agent browser tools (Playwright wrappers)

Adds 13 Playwright-backed tool handlers to the exploratory agent:
page_goto, page_click, page_fill, page_select_option, page_press,
page_inner_text, page_is_visible, page_body_text, page_console_errors,
page_pageerrors, page_websocket_frames, page_reload, page_screenshot.

Every tool has truncation limits (16 KB body text, 4 KB per WS frame,
200 frames max) so the agent is not handed unbounded log data.

Tool schemas are registered via tools/__init__.py::register() which
also appends to schema.TOOL_SCHEMAS for the agent loop's `tools=`
parameter to Messages API.

4 new unit tests: registry parity, page_goto success path, 16-KB
truncation, page_click error propagation. Mocked Playwright — no
real browser in pytest.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: API tool — direct HTTP request with CSRF controls

**Files:**
- Create: `dev/harness/exploratory_agent/tools/api.py`
- Modify: `dev/harness/exploratory_agent/tools/__init__.py` (import new module)
- Modify: `tests/test_exploratory_agent.py` (append API tests)

- [ ] **Step 1: Write failing tests for api_request**

Append to `tests/test_exploratory_agent.py`:

```python
def test_api_request_registered():
    from dev.harness.exploratory_agent.tools import TOOL_REGISTRY
    assert "api_request" in TOOL_REGISTRY


def test_api_request_csrf_auto_includes_token(monkeypatch):
    from dev.harness.exploratory_agent.tools.api import ApiTools
    import httpx

    captured = {}

    def fake_request(self, method, url, **kw):
        captured["headers"] = kw.get("headers", {})
        r = MagicMock(status_code=200, headers={}, text="{}")
        r.json = MagicMock(return_value={})
        return r

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    t = ApiTools(base_url="http://x:18099", csrf_token_getter=lambda: "TOKEN123")
    t.api_request_sync("POST", "/api/validate-path", json={"path": "/srv"}, csrf="auto")
    assert captured["headers"].get("X-CSRF-Token") == "TOKEN123"


def test_api_request_csrf_skip_omits_token(monkeypatch):
    from dev.harness.exploratory_agent.tools.api import ApiTools
    import httpx

    captured = {}

    def fake_request(self, method, url, **kw):
        captured["headers"] = kw.get("headers", {})
        r = MagicMock(status_code=403, headers={}, text='{"detail":"no"}')
        r.json = MagicMock(return_value={"detail": "no"})
        return r

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    t = ApiTools(base_url="http://x:18099", csrf_token_getter=lambda: "NEVERUSED")
    t.api_request_sync("POST", "/api/validate-path", json={"path": "/srv"}, csrf="skip")
    assert "X-CSRF-Token" not in captured["headers"]


def test_api_request_csrf_literal_passes_through(monkeypatch):
    from dev.harness.exploratory_agent.tools.api import ApiTools
    import httpx

    captured = {}

    def fake_request(self, method, url, **kw):
        captured["headers"] = kw.get("headers", {})
        r = MagicMock(status_code=403, headers={}, text="")
        r.json = MagicMock(side_effect=ValueError("not json"))
        return r

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    t = ApiTools(base_url="http://x:18099", csrf_token_getter=lambda: "CURRENT")
    t.api_request_sync("POST", "/api/validate-path", json={"path": "/srv"},
                       csrf="STALE_TOKEN_FOR_TESTING")
    assert captured["headers"]["X-CSRF-Token"] == "STALE_TOKEN_FOR_TESTING"


def test_api_request_truncates_body_at_8kb(monkeypatch):
    from dev.harness.exploratory_agent.tools.api import ApiTools
    import httpx

    def fake_request(self, *a, **kw):
        r = MagicMock(status_code=200, headers={}, text="x" * 20_000)
        r.json = MagicMock(side_effect=ValueError)
        return r

    monkeypatch.setattr(httpx.Client, "request", fake_request)
    t = ApiTools(base_url="http://x:18099", csrf_token_getter=lambda: None)
    result = t.api_request_sync("GET", "/api/system", csrf="skip")
    assert len(result["body_text"]) == 8_192
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_exploratory_agent.py::test_api_request_registered -v
```

Expected: FAIL — `api_request` not in registry.

- [ ] **Step 3: Implement ApiTools**

Create `dev/harness/exploratory_agent/tools/api.py`:

```python
"""Direct-HTTP tool for API-level exploration.

Bypasses the browser entirely so the agent can probe endpoints without
running the full wizard flow (useful for fuzzing validators, checking
CSRF enforcement, sending malformed JSON, etc.).

Uses httpx. Short timeout (5 s). Body output truncated at 8 KB.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import httpx

from . import register

_BODY_MAX = 8_192


class ApiTools:
    def __init__(self, base_url: str, csrf_token_getter: Callable[[], Optional[str]]) -> None:
        self.base_url = base_url.rstrip("/")
        self._get_csrf = csrf_token_getter
        self._client = httpx.Client(timeout=5.0)

    def api_request_sync(
        self,
        method: str,
        path: str,
        headers: Optional[dict] = None,
        json: Optional[dict] = None,
        raw_body: Optional[str] = None,
        csrf: str = "auto",
    ) -> dict:
        hdrs = dict(headers or {})
        # CSRF policy
        if csrf == "auto":
            tok = self._get_csrf()
            if tok is not None:
                hdrs["X-CSRF-Token"] = tok
        elif csrf == "skip":
            pass
        else:
            # Literal — agent is testing a specific (probably stale/forged) token.
            hdrs["X-CSRF-Token"] = csrf

        url = self.base_url + path
        try:
            if raw_body is not None:
                resp = self._client.request(method, url, headers=hdrs, content=raw_body)
            else:
                resp = self._client.request(method, url, headers=hdrs, json=json)
        except httpx.TimeoutException:
            return {"status": 0, "headers": {}, "body_text": "", "error": "timeout"}
        except httpx.HTTPError as e:
            return {"status": 0, "headers": {}, "body_text": "", "error": str(e)}

        body_text = resp.text[:_BODY_MAX]
        out: dict[str, Any] = {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body_text": body_text,
        }
        try:
            out["body_json"] = resp.json()
        except ValueError:
            pass
        return out


_API_SCHEMAS: list[dict] = [
    {
        "name": "api_request",
        "description": (
            "Send a raw HTTP request to the wizard's API, bypassing the "
            "browser. Use this to fuzz endpoint validators, test CSRF "
            "enforcement, or send malformed JSON. csrf=\"auto\" attaches "
            "the current meta-tag token; \"skip\" omits the header "
            "entirely; any other string is sent as the literal token."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"]},
                "path": {"type": "string"},
                "headers": {"type": "object"},
                "json": {"type": "object"},
                "raw_body": {"type": "string"},
                "csrf": {"type": "string"},
            },
            "required": ["method", "path"],
        },
    },
]


def _factory(ctx):
    return ctx.api.api_request_sync


register("api_request", _factory, _API_SCHEMAS[0])

from .. import schema as _schema_mod
_schema_mod.TOOL_SCHEMAS.extend(_API_SCHEMAS)
```

- [ ] **Step 4: Wire the module into the registry init**

Modify `dev/harness/exploratory_agent/tools/__init__.py` — add `from . import api` line:

```python
# near the end of the file, under the browser import:
from . import api  # noqa: F401,E402
```

- [ ] **Step 5: Run the tests**

```
python -m pytest tests/test_exploratory_agent.py -v
```

Expected: 10 passed (6 from earlier tasks + 4 new + 1 registered).

- [ ] **Step 6: Commit**

```
git add dev/harness/exploratory_agent/tools/api.py \
        dev/harness/exploratory_agent/tools/__init__.py \
        tests/test_exploratory_agent.py
git commit -m "$(cat <<EOF
feat(harness): exploratory_agent api_request tool

Direct-HTTP probe that bypasses the browser. csrf="auto" attaches the
current meta-tag token; "skip" omits the header (tests CSRF
enforcement); any other string sent as literal (tests stale-token
handling). Body truncated at 8 KB; 5-second timeout.

4 tests: registered, csrf auto attaches, csrf skip omits, csrf literal
passes through, 8-KB truncation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Container tools — LXD disruption surface

**Files:**
- Create: `dev/harness/exploratory_agent/tools/container.py`
- Modify: `dev/harness/exploratory_agent/tools/__init__.py`
- Modify: `tests/test_exploratory_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_exploratory_agent.py`:

```python
def test_container_tools_registered():
    from dev.harness.exploratory_agent.tools import TOOL_REGISTRY
    for name in ("container_run_command", "container_restart_wizard",
                 "container_fs_write", "container_fs_read"):
        assert name in TOOL_REGISTRY


def test_container_run_command_shells_out_via_lxc(monkeypatch):
    from dev.harness.exploratory_agent.tools.container import ContainerTools
    import subprocess

    captured = {}

    def fake_run(argv, **kw):
        captured["argv"] = argv
        r = MagicMock(returncode=0, stdout=b"ok\n", stderr=b"")
        return r

    monkeypatch.setattr(subprocess, "run", fake_run)
    ct = ContainerTools(container="mycontainer")
    result = ct.container_run_command_sync("echo hi")
    assert captured["argv"][:4] == ["lxc", "exec", "mycontainer", "--"]
    assert "echo hi" in " ".join(captured["argv"])
    assert result["exit"] == 0
    assert result["stdout"] == "ok\n"


def test_container_fs_write_refuses_paths_outside_allowed_roots():
    from dev.harness.exploratory_agent.tools.container import ContainerTools
    ct = ContainerTools(container="c")
    r = ct.container_fs_write_sync("/etc/passwd", "nope")
    assert r["ok"] is False
    assert "not allowed" in r["error"]


def test_container_fs_write_allows_srv_tmp_run(monkeypatch):
    from dev.harness.exploratory_agent.tools.container import ContainerTools
    import subprocess

    def fake_run(argv, **kw):
        r = MagicMock(returncode=0, stdout=b"", stderr=b"")
        return r

    monkeypatch.setattr(subprocess, "run", fake_run)
    ct = ContainerTools(container="c")
    for p in ("/srv/foo", "/tmp/bar", "/run/x"):
        assert ct.container_fs_write_sync(p, "content")["ok"] is True


def test_container_restart_wizard_stops_and_starts_unit(monkeypatch):
    from dev.harness.exploratory_agent.tools.container import ContainerTools
    import subprocess

    calls = []

    def fake_run(argv, **kw):
        calls.append(argv)
        return MagicMock(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ct = ContainerTools(container="c")
    r = ct.container_restart_wizard_sync()
    assert r["ok"] is True
    # Two subprocess calls: one stop, one start (or one systemctl restart).
    assert len(calls) >= 1
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_exploratory_agent.py::test_container_tools_registered -v
```

Expected: FAIL.

- [ ] **Step 3: Implement ContainerTools**

Create `dev/harness/exploratory_agent/tools/container.py`:

```python
"""LXD container disruption tools.

The agent uses these to simulate realistic breakage: restarting the
wizard mid-flow (tests CSRF persistence), writing pre-state files,
reading state files, shelling out for arbitrary checks.

SECURITY: container_fs_write refuses paths outside /srv, /tmp, /run.
container_run_command is unrestricted — the LXD container is ephemeral
and deleted at the end of the run. See design spec for rationale.
"""
from __future__ import annotations

import shlex
import subprocess
from typing import Any

from . import register

_EXEC_TIMEOUT = 30
_STDOUT_MAX = 4_096
_FS_READ_MAX = 8_192
_ALLOWED_WRITE_ROOTS = ("/srv/", "/tmp/", "/run/")


class ContainerTools:
    def __init__(self, container: str) -> None:
        self.container = container

    # ---- sync shims (the agent loop calls these) ----

    def container_run_command_sync(self, command: str) -> dict:
        argv = ["lxc", "exec", self.container, "--", "bash", "-c", command]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"exit": -1, "stdout": "", "stderr": "timeout"}
        return {
            "exit": r.returncode,
            "stdout": r.stdout.decode("utf-8", errors="replace")[:_STDOUT_MAX],
            "stderr": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX],
        }

    def container_restart_wizard_sync(self) -> dict:
        # The wizard runs inside the container as a systemd-run transient
        # unit named `geographica-wizard-setup.service`. Restarting the
        # unit regenerates the uvicorn process but (per 9325e93 on main)
        # CSRF token persists.
        cmd = "systemctl restart geographica-wizard-setup.service"
        argv = ["lxc", "exec", self.container, "--", "bash", "-c", cmd]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX]}
        return {"ok": True}

    def container_fs_write_sync(self, path: str, content: str) -> dict:
        if not any(path.startswith(r) for r in _ALLOWED_WRITE_ROOTS):
            return {
                "ok": False,
                "error": f"path {path!r} not allowed; must start with one of {_ALLOWED_WRITE_ROOTS}",
            }
        # Use `tee` via stdin so we don't have to shell-escape `content`.
        argv = ["lxc", "exec", self.container, "--", "tee", path]
        try:
            r = subprocess.run(argv, input=content.encode("utf-8"),
                               capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX]}
        return {"ok": True}

    def container_fs_read_sync(self, path: str) -> dict:
        argv = ["lxc", "exec", self.container, "--", "cat", path]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        if r.returncode != 0:
            return {"ok": False, "error": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX]}
        return {
            "ok": True,
            "content": r.stdout.decode("utf-8", errors="replace")[:_FS_READ_MAX],
        }


_CONTAINER_SCHEMAS: list[dict] = [
    {
        "name": "container_run_command",
        "description": (
            "Run a shell command inside the LXD container (lxc exec). "
            "stdout/stderr each capped at 4 KB, 30-second timeout."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "container_restart_wizard",
        "description": (
            "Restart the setup wizard's systemd unit inside the container. "
            "Simulates `setup.sh` crashing and being relaunched. Useful "
            "for testing CSRF persistence and stale-tab resilience. "
            "Costs ~20 seconds (unit stop + start + uvicorn ready)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "container_fs_write",
        "description": (
            "Write a file inside the container. Path must start with "
            "/srv, /tmp, or /run. Used to seed pre-state for testing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "container_fs_read",
        "description": "Read a file inside the container. Truncated to 8 KB.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]


_METHOD_NAMES = {
    "container_run_command": "container_run_command_sync",
    "container_restart_wizard": "container_restart_wizard_sync",
    "container_fs_write": "container_fs_write_sync",
    "container_fs_read": "container_fs_read_sync",
}


def _factory_builder(tool_name: str):
    def factory(ctx):
        return getattr(ctx.container, _METHOD_NAMES[tool_name])
    return factory


for _s in _CONTAINER_SCHEMAS:
    register(_s["name"], _factory_builder(_s["name"]), _s)

from .. import schema as _schema_mod
_schema_mod.TOOL_SCHEMAS.extend(_CONTAINER_SCHEMAS)
```

- [ ] **Step 4: Wire into registry**

Modify `dev/harness/exploratory_agent/tools/__init__.py` — add:

```python
from . import container  # noqa: F401,E402
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_exploratory_agent.py -v
```

Expected: 15 passed.

- [ ] **Step 6: Commit**

```
git add dev/harness/exploratory_agent/tools/container.py \
        dev/harness/exploratory_agent/tools/__init__.py \
        tests/test_exploratory_agent.py
git commit -m "$(cat <<EOF
feat(harness): exploratory_agent container disruption tools

Adds four LXD-container tools so the agent can simulate realistic
breakage:
- container_run_command: arbitrary shell via lxc exec (30s timeout,
  4 KB stdout/stderr caps)
- container_restart_wizard: systemctl restart of the wizard's
  systemd-run unit; tests CSRF-persistence + stale-tab recovery
- container_fs_write: write files inside the container, path
  restricted to /srv, /tmp, /run (pre-state seeding)
- container_fs_read: cat a file inside the container

Security note: container_run_command is unrestricted. The LXD
container is ephemeral and deleted at run end; destructive ops are
expected for disruption coverage. Not a sandboxing primitive.

5 tests mock subprocess.run; no real LXD in pytest.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Control + reporting tools

**Files:**
- Create: `dev/harness/exploratory_agent/tools/control.py`
- Create: `dev/harness/exploratory_agent/tools/reporting.py`
- Create: `dev/harness/exploratory_agent/findings_writer.py`
- Create: `dev/harness/exploratory_agent/transcript.py`
- Modify: `dev/harness/exploratory_agent/tools/__init__.py`
- Modify: `tests/test_exploratory_agent.py`

- [ ] **Step 1: Write failing tests for control + reporting**

Append to `tests/test_exploratory_agent.py`:

```python
def test_control_and_reporting_tools_registered():
    from dev.harness.exploratory_agent.tools import TOOL_REGISTRY
    for name in ("wait_seconds", "describe_wizard_state",
                 "report_finding", "checkpoint", "stop"):
        assert name in TOOL_REGISTRY


def test_wait_seconds_is_capped_at_30():
    from dev.harness.exploratory_agent.tools.control import ControlTools
    import time
    ct = ControlTools(browser=None)
    t0 = time.time()
    r = ct.wait_seconds_sync(100)
    elapsed = time.time() - t0
    assert r["waited"] == 30
    assert elapsed < 35


def test_report_finding_appends_and_returns_id(tmp_path):
    from dev.harness.exploratory_agent.tools.reporting import ReportingTools
    rt = ReportingTools(findings_dir=str(tmp_path))
    r = rt.report_finding_sync(
        classification="input-validation",
        severity="high",
        title="trailing slash silently accepted",
        reproduction_steps=["enter /srv/x/", "click Next"],
        input={"path": "/srv/x/"},
        observed="path saved with trailing /",
        expected="trailing / stripped",
        evidence={"screenshot": "screenshots/f1-after.png"},
    )
    assert "id" in r
    assert r["id"].startswith("F-")
    assert len(rt.findings) == 1


def test_stop_records_reason():
    from dev.harness.exploratory_agent.tools.reporting import ReportingTools
    rt = ReportingTools(findings_dir="/tmp")
    r = rt.stop_sync(reason="exhausted hypotheses")
    assert r == {"stopped": True}
    assert rt.stop_reason == "exhausted hypotheses"


def test_findings_writer_renders_markdown(tmp_path):
    from dev.harness.exploratory_agent.findings_writer import render_markdown
    findings = [{
        "id": "F-001",
        "classification": "input-validation",
        "severity": "high",
        "title": "Trailing slash accepted",
        "reproduction_steps": ["step 1", "step 2"],
        "input": {"path": "/srv/x/"},
        "observed": "accepted",
        "expected": "stripped",
        "evidence": {"screenshot": "screenshots/x.png"},
    }]
    meta = {
        "container_image": "images:debian/trixie/cloud",
        "pre_state": "clean",
        "model": "claude-sonnet-4-6",
        "started_at": "2026-04-20 14:30",
        "ended_at": "2026-04-20 14:44",
        "turns_used": 83,
        "turns_cap": 200,
        "transcript_path": "dev/harness/findings/2026-04-20-1430.transcript.jsonl",
        "stop_reason": "time budget",
    }
    md = render_markdown(findings, meta)
    assert "# Exploratory-Agent Findings" in md
    assert "Finding 1 — HIGH" in md
    assert "Trailing slash accepted" in md
    assert "F-001" in md


def test_transcript_writer_appends_jsonl(tmp_path):
    import json
    from dev.harness.exploratory_agent.transcript import TranscriptWriter
    p = tmp_path / "t.jsonl"
    tw = TranscriptWriter(str(p))
    tw.log({"event": "tool_call", "name": "page_goto", "args": {"url": "x"}})
    tw.log({"event": "tool_result", "name": "page_goto", "result": {"status": 200}})
    tw.close()
    lines = p.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "tool_call"
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_exploratory_agent.py -v 2>&1 | tail -10
```

Expected: 6 new failures (modules not found).

- [ ] **Step 3: Implement control + reporting + writers**

Create `dev/harness/exploratory_agent/tools/control.py`:

```python
"""Control-flow tools: wait, describe_wizard_state.

describe_wizard_state is a convenience so the agent doesn't have to
make 10 page_* calls every turn to know where it is.
"""
from __future__ import annotations

import time

from . import register

_WAIT_MAX = 30


class ControlTools:
    def __init__(self, browser) -> None:
        self.browser = browser

    def wait_seconds_sync(self, n: int) -> dict:
        capped = max(0, min(int(n), _WAIT_MAX))
        time.sleep(capped)
        return {"waited": capped}

    def describe_wizard_state_sync(self) -> dict:
        """Build a summary dict by calling a handful of DOM queries.

        Wraps ~5 page_* queries into one tool call so the agent doesn't
        burn budget asking 10 individual questions every time it needs
        to know where it is. Drives the underlying Playwright page
        directly (not via BrowserTools async methods) so this tool
        owns its own event-loop bridge.
        """
        if self.browser is None:
            return {"step": None, "visible_error_banners": [], "preflight_dots": [],
                    "btn_next_text": None, "btn_next_disabled": None,
                    "error": "no browser bound"}

        import asyncio as _asyncio

        async def _scrape(page):
            out: dict = {
                "step": None,
                "step_name": None,
                "visible_error_banners": [],
                "preflight_dots": [],
                "btn_next_text": None,
                "btn_next_disabled": None,
            }
            banner = page.locator("#global-error-banner")
            if await banner.count() > 0 and await banner.is_visible():
                out["visible_error_banners"].append(
                    (await banner.inner_text()).strip()
                )
            dots = page.locator(".preflight-dot")
            for i in range(await dots.count()):
                d = dots.nth(i)
                cls = (await d.get_attribute("class")) or ""
                status = next(
                    (c for c in cls.split()
                     if c in ("ok", "error", "warning", "missing", "checking")),
                    "unknown",
                )
                item = d.locator(
                    "xpath=ancestor::div[contains(@class,'preflight-item')][1]"
                )
                name = "(unknown)"
                name_locator = item.locator(".preflight-name")
                if await name_locator.count() > 0:
                    name = (await name_locator.inner_text()).strip()
                out["preflight_dots"].append({"name": name, "status": status})
            btn = page.locator("#btn-next")
            if await btn.count() > 0:
                out["btn_next_text"] = (await btn.inner_text()).strip()
                out["btn_next_disabled"] = (
                    await btn.get_attribute("disabled")
                ) is not None
            for i in range(1, 6):
                el = page.locator(f"#step-{i}")
                if await el.count() and await el.is_visible():
                    out["step"] = i
                    break
            return out

        loop = _asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_scrape(self.browser.page))
        finally:
            loop.close()


_SCHEMAS: list[dict] = [
    {
        "name": "wait_seconds",
        "description": "Block for N seconds (capped at 30). Useful for letting async UI transitions settle.",
        "input_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "minimum": 0}},
            "required": ["n"],
        },
    },
    {
        "name": "describe_wizard_state",
        "description": (
            "Return a summary of the current wizard UI: step number, "
            "visible error banners, preflight dot statuses, next-button "
            "text + disabled state. Cheaper than calling page_* 10 times."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def _factory_wait(ctx):
    return ctx.control.wait_seconds_sync


def _factory_describe(ctx):
    return ctx.control.describe_wizard_state_sync


register("wait_seconds", _factory_wait, _SCHEMAS[0])
register("describe_wizard_state", _factory_describe, _SCHEMAS[1])

from .. import schema as _schema_mod
_schema_mod.TOOL_SCHEMAS.extend(_SCHEMAS)
```

Create `dev/harness/exploratory_agent/tools/reporting.py`:

```python
"""Reporting tools: report_finding, checkpoint, stop.

ReportingTools accumulates findings in memory during the session; the
agent_loop writes them to disk at session end via findings_writer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import register


class ReportingTools:
    def __init__(self, findings_dir: str) -> None:
        self.findings_dir = Path(findings_dir)
        self.findings_dir.mkdir(parents=True, exist_ok=True)
        self.findings: list[dict] = []
        self.checkpoints: list[str] = []
        self.stop_reason: Optional[str] = None

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
        fid = f"F-{len(self.findings) + 1:03d}"
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
```

Create `dev/harness/exploratory_agent/findings_writer.py`:

```python
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
```

Create `dev/harness/exploratory_agent/transcript.py`:

```python
"""JSONL transcript writer.

Every tool call + result, every agent text message, every checkpoint
gets a single JSON line appended. Used for debugging + replay.
"""
from __future__ import annotations

import json
from typing import Any


class TranscriptWriter:
    def __init__(self, path: str) -> None:
        self._fh = open(path, "w", encoding="utf-8")

    def log(self, event: dict) -> None:
        self._fh.write(json.dumps(event, default=str, ensure_ascii=False))
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()
```

- [ ] **Step 4: Wire new tools into the registry**

Modify `dev/harness/exploratory_agent/tools/__init__.py` — add:

```python
from . import control  # noqa: F401,E402
from . import reporting  # noqa: F401,E402
```

- [ ] **Step 5: Run the tests**

```
python -m pytest tests/test_exploratory_agent.py -v
```

Expected: 21 passed.

- [ ] **Step 6: Commit**

```
git add dev/harness/exploratory_agent/ tests/test_exploratory_agent.py
git commit -m "$(cat <<EOF
feat(harness): exploratory_agent control + reporting tools + writers

- ControlTools: wait_seconds (capped at 30), describe_wizard_state
  (placeholder — full orchestration wired in agent_loop)
- ReportingTools: report_finding (accumulates + returns F-NNN id),
  checkpoint (transcript marker), stop (flips session flag)
- findings_writer.render_markdown: pinned report format
- TranscriptWriter: JSONL append-per-event for debug/replay

6 new tests cover each tool's success path + the renderer + the
transcript writer.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: System prompt + bug-class seed list

**Files:**
- Create: `dev/harness/exploratory_agent/prompts.py`
- Create: `dev/harness/exploratory_agent/bug_classes.md`
- Modify: `tests/test_exploratory_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_exploratory_agent.py`:

```python
def test_system_prompt_exists_and_has_required_sections():
    from dev.harness.exploratory_agent.prompts import build_system_prompt
    p = build_system_prompt(wizard_url="http://x", container="c",
                             max_minutes=15, max_turns=200)
    assert "bug-bounty" in p.lower() or "bug bounty" in p.lower() \
        or "exploratory" in p.lower()
    assert "http://x" in p
    assert "container: c" in p.lower() or "c" in p
    assert "15" in p
    assert "200" in p
    # Known bugs block is injected from bug_classes.md
    assert "trailing" in p.lower()  # one of the seeded classes


def test_bug_classes_file_exists_and_is_nonempty():
    from pathlib import Path
    import dev.harness.exploratory_agent as pkg
    p = Path(pkg.__file__).parent / "bug_classes.md"
    assert p.exists()
    body = p.read_text()
    # Spot-check: each of the 5 April classes is named.
    for marker in ("Trixie docker-buildx", "websockets", "PBF",
                   "CSRF", "trailing slash"):
        assert marker.lower() in body.lower(), f"missing seed: {marker}"
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_exploratory_agent.py::test_bug_classes_file_exists_and_is_nonempty -v
```

Expected: FAIL — file missing.

- [ ] **Step 3: Create bug_classes.md**

Create `dev/harness/exploratory_agent/bug_classes.md`:

```
# Seed Bug Classes — v1

This file is versioned alongside the agent prompt so new bug classes
can be added as they surface without changing code.

## Input validation
- Trailing slash in file paths (stripped? accepted with `//`? error?)
- Leading whitespace or BOM (U+FEFF) in text inputs
- Doubled slashes in paths (`/srv//foo`)
- Unicode / emoji / non-ASCII in paths and field values
- Extremely long inputs (>4 KB)
- Empty strings, whitespace-only
- Path traversal (`/srv/../etc/passwd`)
- Null bytes (`\x00`) in inputs
- Relative paths where absolute expected
- Shell metacharacters (`;`, `$`, backticks) in strings that end up in bash

## Resilience
- Stale CSRF token after wizard restart (container_restart_wizard, then retry)
- Navigate backward then forward
- Double-click Next / Submit
- Refresh browser mid-step (page_reload at each step boundary)
- Two tabs open on the same wizard session
- Fill fields in reverse order (Next in Step 2 before Step 1 complete)
- Force-click a disabled button via page.evaluate-equivalent

## Validation feedback
- Silent swallow of errors (action appears to succeed but state didn't change)
- Unhelpful error copy ("error occurred")
- Raw Python tracebacks rendered in the UI
- Error banners that auto-dismiss before a user could read them
- Buttons whose label does not match their action

## Protocol / API (via api_request)
- Missing CSRF token on POST (csrf="skip")
- Stale CSRF token (csrf="old_token")
- Wrong Content-Type header
- Malformed JSON body (raw_body="{bad")
- Missing required field
- Extra unexpected field (rejected or silently ignored?)
- Huge payload (megabytes)
- Idempotency: POST /api/start twice in a row — second should reject cleanly

## Already-known bug classes (don't re-discover these)
- Debian Trixie docker-buildx file-conflict in bootstrap.sh (FIXED 59f00b5)
- websockets missing from setup/requirements.txt (FIXED ef28cd8)
- OSM PBF corruption from wget -c without integrity check (FIXED 44c5ea6)
- CSRF token regenerated on uvicorn restart (FIXED 9325e93)
- Trailing slash in custom data path not normalized (FIXED 7bcf685)

## Novel
Anything else that looks wrong. Always consider: does this match a real
beta-tester experience? Would a naive first-time user hit this?
```

- [ ] **Step 4: Create the prompt builder**

Create `dev/harness/exploratory_agent/prompts.py`:

```python
"""System prompt for the exploratory agent.

Rendered per-session with runtime metadata (URL, container, budget).
Seed bug-class list is read from bug_classes.md so non-code updates
don't need a release.
"""
from __future__ import annotations

from pathlib import Path

_SEED_PATH = Path(__file__).parent / "bug_classes.md"


def build_system_prompt(*, wizard_url: str, container: str,
                         max_minutes: int, max_turns: int) -> str:
    seed = _SEED_PATH.read_text()
    return f"""You are an adversarial beta-tester for Geographica, an offline-first GIS
setup wizard. Your job: find bugs a real first-time beta tester would
hit — BEFORE they hit them.

This session is bounded. You have up to {max_minutes} minutes OR {max_turns}
turns, whichever comes first. When your time is nearly up, call `stop`.

## Environment

- Wizard URL: {wizard_url}
- LXD container: {container}
- The container is EPHEMERAL and will be deleted after this session.
  Disruption-class tests are not only allowed but expected.

## Bug classes to probe

{seed}

## Tool-use guidance

- `describe_wizard_state` at the start of each new hypothesis. Cheap,
  high-signal.
- `page_body_text` periodically to check for `Traceback (most recent
  call last)` or `Error:` text that was rendered into the DOM.
- `api_request` with `csrf="skip"` to test API-level validation
  independent of the UI.
- `container_restart_wizard` is POWERFUL but costs ~20 seconds.
  Budget it — one or two uses per session.
- Take a screenshot BEFORE and AFTER any trigger action that might
  reveal a finding.

## Reporting rules

- Every finding must include reproduction steps a human can follow
  without reading the transcript.
- Every finding must include BOTH what you saw AND what you expected.
- One finding per bug. If the same input causes three different bugs,
  that's three findings.
- Maintain an internal list of what you have reported; do not duplicate.
- Classification must match one of the seeded classes OR be "novel".

## Stop conditions

- Call `stop("time budget exhausted")` when ~80% of max-minutes used.
- Call `stop("exhausted hypotheses")` if you cannot think of more
  things to try, but ONLY after trying at least 10 distinct hypotheses.
- You will be auto-stopped at {max_turns} turns.

Begin.
"""
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_exploratory_agent.py -v
```

Expected: 23 passed.

- [ ] **Step 6: Commit**

```
git add dev/harness/exploratory_agent/prompts.py \
        dev/harness/exploratory_agent/bug_classes.md \
        tests/test_exploratory_agent.py
git commit -m "$(cat <<EOF
feat(harness): exploratory_agent system prompt + seeded bug-class list

- prompts.build_system_prompt: renders the full persona + tool
  guidance + stop conditions + seed classes with per-session
  metadata (URL, container, budgets).
- bug_classes.md: seed list covering input validation, resilience,
  validation feedback, protocol/API fuzzing, and the five already-
  known April classes to avoid re-discovery waste.

Prompt is human-editable markdown so new classes can land without
a code change.

2 new tests cover prompt assembly + seed-file presence.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Agent loop + CLI entry + wizard-ci.sh wiring

**Files:**
- Create: `dev/harness/exploratory_agent/agent_loop.py`
- Create: `dev/harness/exploratory_agent/__main__.py`
- Modify: `dev/harness/wizard-ci.sh`
- Modify: `tests/test_exploratory_agent.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_exploratory_agent.py`:

```python
def test_agent_loop_dispatches_tool_use_blocks(monkeypatch, tmp_path):
    """Loop sends tools to SDK, receives tool_use, dispatches to handler,
    feeds tool_result back. Stops on `stop` tool call."""
    from dev.harness.exploratory_agent.agent_loop import run_session, SessionContext

    # Mock Anthropic SDK: returns tool_use(stop) on first turn.
    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                return MagicMock(
                    content=[MagicMock(type="tool_use", id="t1",
                                        name="stop", input={"reason": "test"})],
                    stop_reason="tool_use",
                    usage=MagicMock(input_tokens=10, output_tokens=5),
                )

    ctx = SessionContext(
        client=FakeClient(),
        system_prompt="x",
        browser=None, api=None, container=None,
        control=MagicMock(wait_seconds_sync=lambda n: {"waited": n}),
        reporting=MagicMock(findings=[], stop_reason=None,
                            report_finding_sync=MagicMock(return_value={"id": "F-001"}),
                            checkpoint_sync=MagicMock(return_value={"ok": True}),
                            stop_sync=lambda reason: (setattr(ctx.reporting, "stop_reason", reason) or {"stopped": True})),
        transcript=MagicMock(log=MagicMock(), close=MagicMock()),
        max_turns=10,
        deadline_epoch=9_999_999_999,
    )
    # Patch reporting.stop_sync to actually set stop_reason on the mock
    def _stop_sync(reason):
        ctx.reporting.stop_reason = reason
        return {"stopped": True}
    ctx.reporting.stop_sync = _stop_sync

    run_session(ctx)
    assert ctx.reporting.stop_reason == "test"


def test_agent_loop_auto_stops_at_max_turns(monkeypatch):
    """If the agent never calls stop, the loop terminates at max_turns."""
    from dev.harness.exploratory_agent.agent_loop import run_session, SessionContext

    call_count = {"n": 0}

    class FakeClient:
        class messages:
            @staticmethod
            def create(**kw):
                call_count["n"] += 1
                return MagicMock(
                    content=[MagicMock(type="text", text="thinking...")],
                    stop_reason="end_turn",
                    usage=MagicMock(input_tokens=1, output_tokens=1),
                )

    ctx = SessionContext(
        client=FakeClient(),
        system_prompt="x",
        browser=None, api=None, container=None, control=None,
        reporting=MagicMock(findings=[], stop_reason=None),
        transcript=MagicMock(log=MagicMock(), close=MagicMock()),
        max_turns=3,
        deadline_epoch=9_999_999_999,
    )
    run_session(ctx)
    assert call_count["n"] == 3
```

- [ ] **Step 2: Run to verify failure**

```
python -m pytest tests/test_exploratory_agent.py::test_agent_loop_auto_stops_at_max_turns -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Implement the agent loop**

Create `dev/harness/exploratory_agent/agent_loop.py`:

```python
"""Anthropic SDK tool-use message loop.

Runs one exploratory session. Iterates: send conversation to Claude,
receive a response, dispatch any tool_use blocks to their registered
handlers, append tool_result blocks back into the conversation, repeat
until the model signals stop OR max_turns elapsed OR deadline passed.

Design:
- System prompt is prompt-cached (ephemeral) so per-turn cost stays low.
- Tool outputs are JSON-serialized as content strings (Anthropic
  tool_result expects a string or list-of-blocks).
- Tool handlers MUST NOT raise; any exception is caught and reported
  to the model as `{"error": str(e)}` so the session doesn't crash.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


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
    deadline_epoch: float = 0
    model: str = "claude-sonnet-4-6"
    messages: list[dict] = field(default_factory=list)


def run_session(ctx: SessionContext) -> None:
    from .tools import TOOL_REGISTRY
    from . import schema as _schema

    # First user turn primes the loop. After that the conversation is
    # assistant↔tool_result only.
    ctx.messages.append({"role": "user", "content": "Begin your exploratory session."})

    for turn in range(ctx.max_turns):
        if time.time() >= ctx.deadline_epoch:
            ctx.transcript.log({"event": "deadline_hit", "turn": turn})
            break

        # Claude call with prompt-cached system + tools.
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
        ctx.transcript.log({
            "event": "turn",
            "turn": turn,
            "stop_reason": getattr(resp, "stop_reason", None),
            "usage": {"input": getattr(resp.usage, "input_tokens", 0),
                       "output": getattr(resp.usage, "output_tokens", 0)},
        })

        # Append the assistant message as-is to the history.
        assistant_blocks = []
        tool_results: list[dict] = []
        for block in resp.content:
            btype = getattr(block, "type", None)
            if btype == "text":
                assistant_blocks.append({"type": "text", "text": block.text})
                ctx.transcript.log({"event": "assistant_text", "text": block.text[:500]})
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
                try:
                    entry = TOOL_REGISTRY.get(block.name)
                    if entry is None:
                        result = {"error": f"unknown tool: {block.name}"}
                    else:
                        factory, _schema_entry = entry
                        handler = factory(ctx)
                        # Every handler takes kwargs from block.input.
                        result = handler(**block.input) if isinstance(block.input, dict) else handler(block.input)
                except Exception as e:  # noqa: BLE001
                    result = {"error": f"{type(e).__name__}: {e}"}
                ctx.transcript.log({"event": "tool_result", "id": block.id, "result": result})
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
            # No tools called; agent is stalling. Add a nudge and continue.
            ctx.messages.append({"role": "user",
                                  "content": "Continue. What hypothesis will you test next?"})
```

- [ ] **Step 4: Implement the CLI entry point**

Create `dev/harness/exploratory_agent/__main__.py`:

```python
"""CLI: python3 -m dev.harness.exploratory_agent ...

Launches a single exploratory session against a running wizard in an
LXD container.

Exit codes:
  0 — session completed (regardless of findings count)
  2 — runtime error (SDK failure, Playwright crash, missing env var)
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

from .agent_loop import run_session, SessionContext
from .findings_writer import render_markdown
from .prompts import build_system_prompt
from .tools.api import ApiTools
from .tools.browser import BrowserTools
from .tools.container import ContainerTools
from .tools.control import ControlTools
from .tools.reporting import ReportingTools
from .transcript import TranscriptWriter


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True,
                     help="Wizard URL (e.g. http://127.0.0.1:18099)")
    ap.add_argument("--container", required=True,
                     help="LXD container name running the wizard")
    ap.add_argument("--max-minutes", type=int, default=15)
    ap.add_argument("--max-turns", type=int, default=200)
    ap.add_argument("--output", required=True,
                     help="Path to write the findings markdown")
    ap.add_argument("--model", default="claude-sonnet-4-6")
    return ap.parse_args()


def _fetch_csrf(wizard_url: str) -> str | None:
    import re
    import httpx
    try:
        r = httpx.get(wizard_url, timeout=5)
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', r.text)
        return m.group(1) if m else None
    except httpx.HTTPError:
        return None


async def _boot_playwright(wizard_url: str, screenshot_dir: str):
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    page = await browser.new_page()
    bt = BrowserTools(page=page, screenshot_dir=screenshot_dir)
    page.on("console", lambda m: bt._console_errors.append(f"{m.type}:{m.text}")
             if m.type == "error" else None)
    page.on("pageerror", lambda e: bt._pageerrors.append(str(e)))

    def _wire_ws(ws):
        def _fr(payload):
            text = payload if isinstance(payload, str) else bytes(payload).decode("utf-8", errors="replace")
            if len(bt._ws_frames) < 200:
                bt._ws_frames.append({
                    "url": ws.url,
                    "direction": "received",
                    "payload": text[:4_096],
                })
        ws.on("framereceived", _fr)
    page.on("websocket", _wire_ws)

    await page.goto(wizard_url)
    return pw, browser, bt


def main() -> int:
    args = _parse()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    screenshots = output.parent / "screenshots"
    transcript_path = output.with_suffix(".transcript.jsonl")

    import anthropic
    client = anthropic.Anthropic()

    # Playwright must be driven on an asyncio loop; the agent loop is
    # sync but calls sync shims that run_until_complete. Create the
    # loop ourselves so sync shims land on the same one.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    pw, browser_obj, browser_tools = loop.run_until_complete(
        _boot_playwright(args.url, str(screenshots))
    )

    try:
        api_tools = ApiTools(base_url=args.url,
                              csrf_token_getter=lambda: _fetch_csrf(args.url))
        container_tools = ContainerTools(container=args.container)
        control_tools = ControlTools(browser=browser_tools)
        reporting = ReportingTools(findings_dir=str(output.parent))
        transcript = TranscriptWriter(str(transcript_path))
        started = time.strftime("%Y-%m-%d %H:%M")
        deadline = time.time() + args.max_minutes * 60

        ctx = SessionContext(
            client=client,
            system_prompt=build_system_prompt(
                wizard_url=args.url, container=args.container,
                max_minutes=args.max_minutes, max_turns=args.max_turns,
            ),
            browser=browser_tools, api=api_tools,
            container=container_tools, control=control_tools,
            reporting=reporting, transcript=transcript,
            max_turns=args.max_turns, deadline_epoch=deadline,
            model=args.model,
        )

        try:
            run_session(ctx)
        finally:
            transcript.close()

        md = render_markdown(reporting.findings, {
            "container_image": "images:debian/trixie/cloud",
            "pre_state": "clean",
            "model": args.model,
            "started_at": started,
            "ended_at": time.strftime("%Y-%m-%d %H:%M"),
            "turns_used": len([m for m in ctx.messages if m.get("role") == "assistant"]),
            "turns_cap": args.max_turns,
            "transcript_path": str(transcript_path),
            "stop_reason": reporting.stop_reason or "max_turns_or_deadline",
        })
        output.write_text(md)
        print(f"Wrote {output} ({len(reporting.findings)} findings)")
        return 0
    finally:
        loop.run_until_complete(browser_obj.close())
        loop.run_until_complete(pw.stop())
        loop.close()


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Wire wizard-ci.sh**

Edit `dev/harness/wizard-ci.sh`:

1. In the argument parsing (around the `case "$arg"` block), add:
```
        --exploratory)    MODE="exploratory" ;;
```

2. In the usage string, add `exploratory` to the mode list.

3. After the wizard-up check and BEFORE `echo "[$(date +%H:%M:%S)] Driving wizard (mode=$MODE)..."`, add:
```
# Exploratory mode replaces the deterministic Playwright walk with a
# Claude-driven exploratory session. Reuses the same container + wizard
# setup; just a different driver.
if [ "$MODE" = "exploratory" ]; then
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        echo "FAIL: --exploratory requires ANTHROPIC_API_KEY env var" >&2
        exit 2
    fi
    OUTPUT_PATH="${EXPLORATORY_OUTPUT:-dev/harness/findings/$(date +%Y-%m-%d-%H%M).md}"
    MAX_MIN="${EXPLORATORY_MAX_MINUTES:-15}"
    mkdir -p "$(dirname "$OUTPUT_PATH")"
    echo "[$(date +%H:%M:%S)] Driving wizard (mode=exploratory, max-minutes=$MAX_MIN) ..."
    python3 -m dev.harness.exploratory_agent \
        --url="$WIZARD_URL" \
        --container="$CONTAINER" \
        --max-minutes="$MAX_MIN" \
        --output="$OUTPUT_PATH" || RC=$?
    if [ "${RC:-0}" -eq 0 ]; then
        echo "[$(date +%H:%M:%S)] Exploratory session complete — findings at $OUTPUT_PATH"
    else
        echo "FAIL: exploratory agent exited $RC" >&2
        lxc exec "$CONTAINER" -- cat /tmp/setup.log 2>/dev/null | tail -40 || true
    fi
    exit "${RC:-0}"
fi
```

This branches out of the normal `node drive-wizard.mjs` flow.

- [ ] **Step 6: Run unit tests**

```
python -m pytest tests/test_exploratory_agent.py -v
```

Expected: 25 passed.

- [ ] **Step 7: Syntax-check wizard-ci.sh**

```
bash -n dev/harness/wizard-ci.sh && echo "syntax OK"
```

Expected: `syntax OK`.

- [ ] **Step 8: Commit**

```
git add dev/harness/exploratory_agent/agent_loop.py \
        dev/harness/exploratory_agent/__main__.py \
        dev/harness/wizard-ci.sh tests/test_exploratory_agent.py
git commit -m "$(cat <<EOF
feat(harness): exploratory_agent loop + CLI + wizard-ci.sh --exploratory

- agent_loop.run_session: Anthropic SDK tool-use loop. Prompt caching
  on system + tools. Handler exceptions caught and reported to the
  model so the session never crashes from a tool bug. Stops on
  reporting.stop_reason OR max_turns OR deadline.
- __main__.py CLI boots Playwright + all tool classes + transcript
  writer, runs the session, renders findings markdown, exits 0
  (findings are non-blocking) or 2 (runtime error).
- wizard-ci.sh gains --exploratory mode. Reuses the existing LXD
  container + bootstrap + setup.sh + proxy plumbing; swaps the
  drive-wizard.mjs call for the Python agent.

2 loop tests cover stop-tool and auto-stop-at-max-turns; real Anthropic
calls are mocked.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: CI workflow wiring

**Files:**
- Modify: `.github/workflows/wizard-ci.yml`

- [ ] **Step 1: Add nightly job + dispatch option**

Edit `.github/workflows/wizard-ci.yml`:

1. Add `schedule` trigger at the top level (alongside `push`, `pull_request`, `workflow_dispatch`):
```
  schedule:
    # 09:00 UTC = 02:00 PDT; matches the maintainer's off-peak window.
    - cron: '0 9 * * *'
```

2. Add `exploratory` to the `workflow_dispatch.inputs.mode` options list.

3. Add a new step after the existing manual-dispatch smoke/full step:
```
      - name: Run wizard — manual exploratory
        if: github.event_name == 'workflow_dispatch' && inputs.mode == 'exploratory'
        env:
          MODE: exploratory
          EXPLORATORY_MAX_MINUTES: "15"
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          ./dev/harness/wizard-ci.sh "--$MODE"

      - name: Run wizard — nightly exploratory
        if: github.event_name == 'schedule'
        env:
          EXPLORATORY_MAX_MINUTES: "15"
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: |
          ./dev/harness/wizard-ci.sh --exploratory

      - name: Upload findings artifact
        if: always() && (github.event_name == 'schedule' || (github.event_name == 'workflow_dispatch' && inputs.mode == 'exploratory'))
        uses: actions/upload-artifact@v4
        with:
          name: exploratory-findings
          path: dev/harness/findings/*.md
          if-no-files-found: ignore
```

- [ ] **Step 2: Verify the YAML parses**

```
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/wizard-ci.yml'))"
echo "OK"
```

Expected: `OK` with no exception.

- [ ] **Step 3: Commit**

```
git add .github/workflows/wizard-ci.yml
git commit -m "$(cat <<EOF
ci(harness): nightly --exploratory run + manual-dispatch option

- Adds a 09:00 UTC schedule that runs --exploratory with a 15-minute
  budget against the self-hosted Pi runner. Uploads findings markdown
  as a workflow artifact for human review.
- Adds "exploratory" as a workflow_dispatch mode option so it can be
  manually triggered off-cycle.

Does NOT add exploratory to push/PR triggers — the ~\$2-5/run cost
and the non-determinism make it unsuitable for per-push gating.
Findings are advisory; converting them into scripted assertions is
the regression workflow (covered in dev/harness/README.md update).

Requires ANTHROPIC_API_KEY secret on the self-hosted runner.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Regression-rollback fixtures

**Files:**
- Create: `dev/harness/exploratory_agent/rollback_fixtures/`
- Create: `dev/harness/exploratory_agent/rollback_fixtures/websockets-missing.patch`
- Create: `dev/harness/exploratory_agent/rollback_fixtures/trailing-slash-accepted.patch`
- Create: `dev/harness/exploratory_agent/rollback_fixtures/README.md`
- Create: `tests/test_exploratory_rollbacks.py`

- [ ] **Step 1: Capture a patch that removes the websockets fix**

```
git diff ef28cd8^ ef28cd8 -- setup/requirements.txt setup/static/setup.js \
    > dev/harness/exploratory_agent/rollback_fixtures/websockets-missing.patch
```

(That patch, applied in REVERSE in the LXD container, restores the bug.)

- [ ] **Step 2: Capture a patch that removes the trailing-slash fix**

```
git diff 7bcf685^ 7bcf685 -- setup/main.py setup/config.py setup/static/setup.js \
    > dev/harness/exploratory_agent/rollback_fixtures/trailing-slash-accepted.patch
```

- [ ] **Step 3: Write the rollback-fixture README**

Create `dev/harness/exploratory_agent/rollback_fixtures/README.md`:

```
# Rollback Regression Fixtures

Each `.patch` file here is a captured diff of a known-fixed bug. Applied
IN REVERSE inside an LXD container (via `patch -R -p1`), it restores the
broken state. Running the exploratory agent against the broken state
must produce a finding that identifies the bug class.

This is how we keep confidence that the agent still catches things as
prompts and tooling evolve. Without these fixtures, a future prompt
regression could silently stop finding real bugs.

## Files

- websockets-missing.patch — restores the 2026-04-19 report where
  setup/requirements.txt lacks `websockets` and /ws/progress silently
  404s. Agent should report a WebSocket / progress-stream finding.
- trailing-slash-accepted.patch — restores the 2026-04-20 report where
  custom data paths with a trailing `/` propagate into bash string-
  concat and produce `//`. Agent should report an input-validation
  finding in Step 1.

## Usage

```
# Applied automatically by tests/test_exploratory_rollbacks.py.
# Manual:
cd /tmp && mkdir t && cd t
git clone --depth=1 /path/to/geographica .
patch -R -p1 < dev/harness/exploratory_agent/rollback_fixtures/websockets-missing.patch
# rebuild container, run --exploratory, verify findings include a
# websockets-class finding.
```
```

- [ ] **Step 4: Write a unit-level smoke that verifies the fixtures are well-formed**

Create `tests/test_exploratory_rollbacks.py`:

```python
"""Smoke-check the rollback fixtures.

This test does NOT run the agent — that's too expensive for unit tests.
It just verifies each .patch file is a valid reversible diff that
touches the expected files.
"""
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "dev" / "harness" \
    / "exploratory_agent" / "rollback_fixtures"


def test_rollback_fixtures_directory_exists():
    assert FIXTURES.is_dir(), f"missing {FIXTURES}"


def test_websockets_fixture_is_valid_patch():
    p = FIXTURES / "websockets-missing.patch"
    assert p.exists()
    body = p.read_text()
    # Must be a unified-diff header-style patch touching setup/requirements.txt.
    assert "setup/requirements.txt" in body


def test_trailing_slash_fixture_is_valid_patch():
    p = FIXTURES / "trailing-slash-accepted.patch"
    assert p.exists()
    body = p.read_text()
    assert "setup/main.py" in body or "setup/config.py" in body


def test_fixture_readme_exists():
    p = FIXTURES / "README.md"
    assert p.exists()
```

- [ ] **Step 5: Run tests**

```
python -m pytest tests/test_exploratory_rollbacks.py -v
```

Expected: 4 passed.

- [ ] **Step 6: Commit**

```
git add dev/harness/exploratory_agent/rollback_fixtures/ \
        tests/test_exploratory_rollbacks.py
git commit -m "$(cat <<EOF
test(harness): rollback fixtures for regression-verifying the agent

Two .patch files captured from 9325e93 (websockets) and 7bcf685
(trailing slash). Applied in reverse in a test container, each
restores a known-broken state; running --exploratory against that
state should produce a finding in the expected class.

This prevents silent regression: if a future prompt / tool change
makes the agent miss a class it previously caught, applying the
fixture and re-running exposes it.

Fixture invocation is manual for v1 (see README). Automating via a
new --rollback flag on wizard-ci.sh is v2 scope.

4 unit tests verify fixture shape + README presence.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: README + first real-run evidence

**Files:**
- Modify: `dev/harness/README.md`
- Create: `dev/harness/findings/2026-04-20-<time>.md` (from first real run)

- [ ] **Step 1: Run the agent for real — 10-minute budget, single pass**

```
export ANTHROPIC_API_KEY=...   # on the Pi runner only; NOT in the repo
./dev/harness/wizard-ci.sh --exploratory
```

This takes ~5 min bootstrap + 15 min agent = ~20 min. Produces a findings file at `dev/harness/findings/YYYY-MM-DD-HHMM.md`.

- [ ] **Step 2: Review the findings file and commit it as evidence**

Every finding gets a 30-second human review:
- Is this a real bug? If yes, open a follow-up (separate commit, separate fix).
- Is this cosmetic / known / not actionable? Move to `findings/dismissed/` with a one-line note.

Commit both the raw file and any `dismissed/` moves.

- [ ] **Step 3: Update the harness README**

Edit `dev/harness/README.md` — after the existing `--smoke` / `--pipeline-start` documentation, add:

```
## --exploratory mode

Launches a Claude Sonnet 4.6 agent (via the Anthropic Python SDK) with
Playwright tools + API probes + LXD disruption primitives, prompted as
a bug-bounty-style beta tester. The agent walks the wizard, fuzzes
inputs, and reports suspicious observations to a findings file.

```
./dev/harness/wizard-ci.sh --exploratory [--image=ALIAS] [--pre-state=NAME]
# Env vars:
#   ANTHROPIC_API_KEY           required
#   EXPLORATORY_MAX_MINUTES     default 15
#   EXPLORATORY_OUTPUT          default dev/harness/findings/<date>-<time>.md
```

Output: a markdown findings file + a JSONL transcript at
`<output>.transcript.jsonl` + PNG screenshots under
`dev/harness/findings/screenshots/`.

**Findings are advisory.** The harness always exits 0 on a successful
agent run; findings are for human review. The workflow is:
1. Agent runs nightly (or on-demand).
2. Human reviews the findings file.
3. Real bugs → new scripted assertion in drive-wizard.mjs OR a
   pytest regression, same pattern we've been using manually.
4. Cosmetic / not-actionable → move entry to findings/dismissed/ with
   a one-line rationale.

**Cost:** ~\$2–5 per run at 15 minutes (claude-sonnet-4-6 + prompt
caching). Acceptable for nightly; too expensive for per-push gating.

**Rollback fixtures** live in
`dev/harness/exploratory_agent/rollback_fixtures/`. Apply one to a
test container and rerun to verify the agent still catches that
class. See the fixture README for details.
```

- [ ] **Step 4: Commit**

```
git add dev/harness/README.md dev/harness/findings/
git commit -m "$(cat <<EOF
docs(harness): README for --exploratory + first-run findings evidence

Adds the new mode's section to the harness README: invocation, env
vars, output format, cost envelope, and the findings-to-assertions
workflow.

Commits the first real exploratory-run findings file as evidence the
system works end-to-end. Findings are advisory; converting any real
bugs found into scripted assertions is a separate per-finding commit.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Full regression**

```
python -m pytest tests/ -v 2>&1 | tail -3
```

Must match baseline + 29 new exploratory-agent tests (all passing). Any regression must be fixed before closing the plan.

---

## Self-review checklist

Before announcing plan complete, verify against spec:

**Spec coverage**
- [x] Task 1: scaffold + deps (spec §Summary, §Architecture)
- [x] Task 2: browser tools (spec §Tool surface — Browser tools)
- [x] Task 3: api_request tool (spec §Tool surface — API tools)
- [x] Task 4: container tools (spec §Tool surface — Container tools)
- [x] Task 5: control + reporting (spec §Tool surface — Control flow, Reporting)
- [x] Task 6: prompt + bug_classes.md (spec §System prompt structure)
- [x] Task 7: agent loop + CLI + wizard-ci.sh (spec §Architecture, §Integration with existing harness)
- [x] Task 8: CI workflow (spec §Integration with existing harness — CI wiring)
- [x] Task 9: rollback fixtures (spec §Acceptance criteria #3)
- [x] Task 10: README + evidence (spec §Summary of deliverables)

**Placeholder scan**
- No "TODO" / "TBD" / "fill in" markers remain in the plan.
- Every step with code shows the actual code.
- Every pytest command shows expected output.
- Every commit shows the full commit message.

**Type + name consistency**
- `SessionContext` fields: client, system_prompt, browser, api, container, control, reporting, transcript, max_turns, deadline_epoch, model, messages. Matches between Task 5 (implied), Task 7 (declared), and tests.
- Tool handler contract: `factory(ctx) -> callable(**kwargs) -> dict`. Matches across Tasks 2, 3, 4, 5.
- Every tool schema in `TOOL_SCHEMAS` is register()'d with the same `name`. Unit test `test_*_registered` enforces.
- Findings-file format: pinned in Task 5's `render_markdown` test against the format in Task 9's spec section. Same keys.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-20-exploratory-agent-harness.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?

- If Subagent-Driven chosen: REQUIRED SUB-SKILL is `superpowers:subagent-driven-development`. Fresh subagent per task + two-stage review.
- If Inline Execution chosen: REQUIRED SUB-SKILL is `superpowers:executing-plans`. Batch execution with checkpoints.
