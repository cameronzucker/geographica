from pathlib import Path
R = Path(__file__).parent.parent / "dev" / "harness" / "README.md"


def test_readme_exists():
    assert R.exists()


def test_readme_covers_setup_and_usage():
    text = R.read_text()
    assert "npm install" in text or "playwright install" in text
    assert "./wizard-ci.sh" in text or "wizard-ci.sh" in text


def test_readme_mentions_lxd_validation_skill():
    text = R.read_text()
    assert "lxd-validation" in text.lower()
    assert "deterministic" in text.lower() or "complementary" in text.lower()
