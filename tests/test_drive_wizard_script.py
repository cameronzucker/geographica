from pathlib import Path
MJS = Path(__file__).parent.parent / "dev" / "harness" / "drive-wizard.mjs"
PKG = Path(__file__).parent.parent / "dev" / "harness" / "package.json"


def test_mjs_exists():
    assert MJS.exists()


def test_mjs_imports_playwright():
    text = MJS.read_text()
    assert "import" in text and "playwright" in text


def test_mjs_handles_smoke_and_full():
    text = MJS.read_text()
    assert "--smoke" in text
    assert "--full" in text


def test_mjs_drives_all_five_steps():
    text = MJS.read_text()
    for step in ("step-1", "step-2", "step-3", "step-4", "step-5"):
        assert step in text


def test_package_json_has_playwright_devdep():
    import json
    assert PKG.exists()
    data = json.loads(PKG.read_text())
    assert "playwright" in (data.get("devDependencies") or {})
