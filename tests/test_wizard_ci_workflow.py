from pathlib import Path
WF = Path(__file__).parent.parent / ".github" / "workflows" / "wizard-ci.yml"


def test_workflow_exists():
    assert WF.exists()


def test_workflow_is_manual_dispatch_only():
    text = WF.read_text()
    assert "workflow_dispatch" in text
    # Schedule block either absent or commented out
    assert "\nschedule:" not in text or "# schedule:" in text


def test_workflow_runs_harness():
    text = WF.read_text()
    assert "wizard-ci.sh" in text
