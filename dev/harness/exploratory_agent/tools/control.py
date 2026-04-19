"""Control-flow tools: wait, describe_wizard_state.

describe_wizard_state is a convenience so the agent doesn't have to
make 10 page_* calls every turn to know where it is.
"""
from __future__ import annotations

import asyncio
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

        MUST-FIX 1.3: real implementation (not a stub). Drives the
        underlying Playwright page directly via a dedicated event loop
        (same pattern as BrowserTools._sync shims per MUST-FIX 1.1).
        """
        if self.browser is None:
            return {"step": None, "step_name": None,
                    "visible_error_banners": [],
                    "preflight_dots": [],
                    "btn_next_text": None, "btn_next_disabled": None,
                    "error": "no browser bound"}

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

        loop = asyncio.new_event_loop()
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
