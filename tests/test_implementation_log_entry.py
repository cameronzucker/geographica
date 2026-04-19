from pathlib import Path
LOG = Path(__file__).parent.parent / "dev" / "implementation-log.md"


def test_log_has_today_setup_entry():
    text = LOG.read_text()
    # Could be 2026-04-18 (plan date) or 2026-04-19 (execution date)
    assert "2026-04-18" in text or "2026-04-19" in text
    assert "setup process remediation" in text.lower() or \
           "setup remediation" in text.lower()
    assert "B1" in text or "48 bugs" in text
