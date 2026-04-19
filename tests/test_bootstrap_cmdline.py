from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_bootstrap_guards_cmdline_sed():
    text = BOOTSTRAP.read_text()
    assert "if [ -f /boot/firmware/cmdline.txt ]" in text or \
           '[ -f /boot/firmware/cmdline.txt ]' in text
    assert "/boot/cmdline.txt" in text
