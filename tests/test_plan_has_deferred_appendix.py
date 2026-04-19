from pathlib import Path
PLAN = Path(__file__).parent.parent / "docs" / "superpowers" / "plans" / \
       "2026-04-18-setup-process-remediation.md"


def test_plan_has_deferred_section():
    text = PLAN.read_text()
    assert "## Deferred bugs" in text or "## Appendix" in text
    for b in ("B44", "B45", "B46", "B47", "B48"):
        assert b in text
