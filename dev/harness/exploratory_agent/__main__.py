"""CLI: python3 -m dev.harness.exploratory_agent ...

Launches a single exploratory session against a running wizard in an
LXD container.

Exit codes:
  0 - session completed (regardless of findings count)
  2 - runtime error (SDK failure, Playwright crash, missing env var)
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
    ap.add_argument("--max-input-tokens", type=int, default=2_000_000)
    ap.add_argument("--max-output-tokens", type=int, default=200_000)
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
            max_input_tokens=args.max_input_tokens,
            max_output_tokens=args.max_output_tokens,
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
