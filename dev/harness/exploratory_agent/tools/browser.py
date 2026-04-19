"""Playwright-backed browser tool handlers for the exploratory agent.

Each tool has an async implementation and a `_sync` shim that creates a
fresh event loop (asyncio.new_event_loop()) and closes it in finally.
This pattern is required for Python 3.13+ compatibility — get_event_loop()
is deprecated and raises on 3.14.

Tools are registered via register() at module import time; schemas are
appended to schema.TOOL_SCHEMAS so the agent loop can pass them verbatim
to the Anthropic Messages API.
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from . import register

_BODY_TEXT_MAX = 16_384
_WS_FRAME_MAX = 4_096
_WS_FRAMES_CAP = 200


class BrowserTools:
    """Wraps a Playwright page with tool-shaped async methods + sync shims."""

    def __init__(self, page: Any, screenshot_dir: str) -> None:
        self.page = page
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        self._console_errors: list[str] = []
        self._pageerrors: list[str] = []
        self._ws_frames: list[dict] = []

        # Wire up listeners if the page supports it (skipped in unit tests
        # where page is a MagicMock that doesn't call callbacks).
        try:
            self.page.on("console", self._on_console)
            self.page.on("pageerror", self._on_pageerror)
            self.page.on("websocket", self._on_websocket)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Event listeners
    # ------------------------------------------------------------------

    def _on_console(self, msg: Any) -> None:
        if getattr(msg, "type", None) == "error":
            self._console_errors.append(str(msg.text))

    def _on_pageerror(self, exc: Any) -> None:
        self._pageerrors.append(str(exc))

    def _on_websocket(self, ws: Any) -> None:
        def _on_frame(frame: Any) -> None:
            if len(self._ws_frames) >= _WS_FRAMES_CAP:
                return
            payload = str(getattr(frame, "payload", ""))[:_WS_FRAME_MAX]
            self._ws_frames.append({"payload": payload})

        try:
            ws.on("framereceived", _on_frame)
            ws.on("framesent", _on_frame)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Async implementations
    # ------------------------------------------------------------------

    async def page_goto(self, url: str) -> dict:
        """Navigate to URL. Returns status + final_url."""
        try:
            response = await self.page.goto(url)
            status = response.status if response is not None else 0
            return {"status": status, "final_url": self.page.url}
        except Exception as exc:
            return {"status": 0, "final_url": "", "error": str(exc)}

    async def page_click(self, selector: str) -> dict:
        """Click a DOM element. 5-second timeout."""
        try:
            await self.page.click(selector, timeout=5_000)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def page_fill(self, selector: str, value: str) -> dict:
        """Fill an input. 5-second timeout."""
        try:
            await self.page.fill(selector, value, timeout=5_000)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def page_select_option(self, selector: str, value: str) -> dict:
        """Select an <option> by value. 5-second timeout."""
        try:
            await self.page.select_option(selector, value, timeout=5_000)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def page_press(self, selector: str, key: str) -> dict:
        """Press a keyboard key. 5-second timeout."""
        try:
            await self.page.press(selector, key, timeout=5_000)
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def page_inner_text(self, selector: str) -> dict:
        """Return innerText of an element, truncated to 16 KB. 5-second timeout."""
        try:
            text = await self.page.inner_text(selector, timeout=5_000)
            return {"ok": True, "text": text[:_BODY_TEXT_MAX]}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def page_is_visible(self, selector: str) -> dict:
        """Check if a selector matches a currently-visible element."""
        try:
            visible = await self.page.is_visible(selector)
            return {"ok": True, "visible": visible}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    async def page_body_text(self) -> dict:
        """Return document.body.innerText truncated to 16 KB."""
        text = await self.page.inner_text("body")
        return {"text": text[:_BODY_TEXT_MAX]}

    async def page_console_errors(self) -> dict:
        """Return all console.error events observed this session."""
        return {"errors": list(self._console_errors)}

    async def page_pageerrors(self) -> dict:
        """Return all uncaught pageerror events observed this session."""
        return {"errors": list(self._pageerrors)}

    async def page_websocket_frames(self) -> dict:
        """Return WebSocket frames observed this session (capped at 200, each truncated to 4 KB)."""
        return {"frames": list(self._ws_frames)}

    async def page_reload(self) -> dict:
        """Reload the current page."""
        try:
            response = await self.page.reload()
            status = response.status if response is not None else 0
            return {"status": status}
        except Exception as exc:
            return {"status": 0, "error": str(exc)}

    async def page_screenshot(self, label: str) -> dict:
        """Take a full-page PNG screenshot tagged with label. Returns output path."""
        safe = re.sub(r"[^a-zA-Z0-9_-]", "_", label)[:64]
        ts = int(time.time() * 1000)
        path = self.screenshot_dir / f"{ts}-{safe}.png"
        await self.page.screenshot(path=str(path), full_page=True)
        return {"path": str(path)}

    # ------------------------------------------------------------------
    # Sync shims — each creates a fresh event loop and closes it in finally.
    # Never uses asyncio.get_event_loop() (deprecated in 3.13, raises in 3.14).
    # ------------------------------------------------------------------

    def page_goto_sync(self, url: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_goto(url))
        finally:
            loop.close()

    def page_click_sync(self, selector: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_click(selector))
        finally:
            loop.close()

    def page_fill_sync(self, selector: str, value: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_fill(selector, value))
        finally:
            loop.close()

    def page_select_option_sync(self, selector: str, value: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_select_option(selector, value))
        finally:
            loop.close()

    def page_press_sync(self, selector: str, key: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_press(selector, key))
        finally:
            loop.close()

    def page_inner_text_sync(self, selector: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_inner_text(selector))
        finally:
            loop.close()

    def page_is_visible_sync(self, selector: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_is_visible(selector))
        finally:
            loop.close()

    def page_body_text_sync(self) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_body_text())
        finally:
            loop.close()

    def page_console_errors_sync(self) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_console_errors())
        finally:
            loop.close()

    def page_pageerrors_sync(self) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_pageerrors())
        finally:
            loop.close()

    def page_websocket_frames_sync(self) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_websocket_frames())
        finally:
            loop.close()

    def page_reload_sync(self) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_reload())
        finally:
            loop.close()

    def page_screenshot_sync(self, label: str) -> dict:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(self.page_screenshot(label))
        finally:
            loop.close()


# ------------------------------------------------------------------
# Tool schemas
# ------------------------------------------------------------------

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


# ------------------------------------------------------------------
# Registration
# ------------------------------------------------------------------

def _factory_builder(method_name: str):
    def factory(ctx):
        return getattr(ctx.browser, method_name)
    return factory


for _schema in _BROWSER_SCHEMAS:
    register(_schema["name"], _factory_builder(_schema["name"] + "_sync"), _schema)

from .. import schema as _schema_mod  # noqa: E402
_schema_mod.TOOL_SCHEMAS.extend(_BROWSER_SCHEMAS)
