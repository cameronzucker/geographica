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
    assert len(calls) >= 1


def test_container_restart_unit_name_matches_wizard_ci_sh():
    """Adversarial-review 1.5: wizard-ci.sh systemd-run --unit=NAME must
    match the WIZARD_SYSTEMD_UNIT constant in container.py. Soft-coupling
    guard against accidental drift.
    """
    import re
    from pathlib import Path
    ci_sh = (Path(__file__).parent.parent / "dev" / "harness" / "wizard-ci.sh").read_text()
    m = re.search(r"--unit=(\S+)", ci_sh)
    assert m, "wizard-ci.sh no longer uses systemd-run --unit=..."
    ci_unit = m.group(1).strip("'\"")
    from dev.harness.exploratory_agent.tools.container import WIZARD_SYSTEMD_UNIT
    # ci_sh may or may not include the `.service` suffix. Accept both.
    assert ci_unit == WIZARD_SYSTEMD_UNIT or ci_unit + ".service" == WIZARD_SYSTEMD_UNIT, (
        f"wizard-ci.sh uses unit {ci_unit!r}; ContainerTools uses {WIZARD_SYSTEMD_UNIT!r}"
    )


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


def test_report_finding_dedups_on_identical_title_and_input(tmp_path):
    """MUST-FIX 4.2: two reports with the same class/title/input keys
    produce ONE finding; second call returns the first ID + deduped=True."""
    from dev.harness.exploratory_agent.tools.reporting import ReportingTools
    rt = ReportingTools(findings_dir=str(tmp_path))
    r1 = rt.report_finding_sync(
        classification="input-validation",
        severity="high",
        title="Trailing slash silently accepted",
        reproduction_steps=["step a"],
        input={"path": "/srv/x/"},
        observed="x",
        expected="y",
        evidence={},
    )
    r2 = rt.report_finding_sync(
        classification="input-validation",
        severity="medium",  # even with different severity
        title="trailing slash   silently  accepted!",  # re-cased + punctuation
        reproduction_steps=["step b"],
        input={"path": "/srv/different/"},  # same KEY, different VALUE
        observed="x2",
        expected="y2",
        evidence={},
    )
    assert r1["id"] == r2["id"]
    assert r2.get("deduped") is True
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
