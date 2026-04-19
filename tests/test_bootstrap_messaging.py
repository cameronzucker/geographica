from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_next_step_appears_at_most_once_per_branch():
    text = BOOTSTRAP.read_text()
    idx = text.find("Bootstrap complete")
    assert idx != -1
    tail = text[idx:]
    assert tail.count('Next step:') == 1


def test_bootstrap_mentions_logout_before_setup():
    assert "Log out" in BOOTSTRAP.read_text()
