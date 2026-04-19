import re
from pathlib import Path
BOOTSTRAP = Path(__file__).parent.parent / "bootstrap.sh"


def test_no_legacy_docker_compose_package():
    text = BOOTSTRAP.read_text()
    for line in text.splitlines():
        if "apt install" not in line and "apt-get install" not in line:
            continue
        tokens = re.findall(r"[\w.-]+", line)
        for tok in tokens:
            assert tok != "docker-compose", f"legacy v1 compose: {line}"


def test_installs_compose_plugin_or_docker_ce():
    text = BOOTSTRAP.read_text()
    assert "docker-compose-plugin" in text or "docker-compose-v2" in text


def test_docker_repo_guard_covers_both_asc_and_gpg():
    """The idempotency guard must skip repo-setup if EITHER keyring file
    exists. Docker's official installer uses .asc; our bootstrap uses .gpg.
    Without checking both, a Pi that previously ran Docker's official
    installer gets a duplicate repo + orphan keyring on re-bootstrap."""
    text = BOOTSTRAP.read_text()
    assert "docker.gpg" in text
    assert "docker.asc" in text
    # The two-file guard should appear on the same line (both conditions anded)
    assert "/etc/apt/keyrings/docker.gpg" in text
    # Either form of `&& [` or an `-o` inside a single `[` is acceptable
    guarded = any(
        ("docker.gpg" in line and "docker.asc" in line and
         ("&&" in line or "-o" in line))
        for line in text.splitlines()
    )
    assert guarded, "Keyring guard must check both docker.gpg AND docker.asc"
