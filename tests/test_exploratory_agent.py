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
