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


def test_removes_conflicting_debian_docker_packages_before_install():
    """Debian 13 (trixie) ships native `docker-buildx` (0.13.1+ds1-3) and
    `docker-compose` (2.26.1-4) packages. Both own the exact paths that
    Docker's `docker-buildx-plugin` and `docker-compose-plugin` claim
    (/usr/libexec/docker/cli-plugins/docker-{buildx,compose}). Neither
    side declares Replaces, so if either is preinstalled on the target
    Pi, `apt install docker-ce docker-compose-plugin` aborts mid-unpack
    with `trying to overwrite ... which is also in package docker-buildx`.

    Every beta tester on Raspberry Pi OS Trixie with any prior Docker
    attempt hits this (observed 2026-04-19). Fix: bootstrap must remove
    the conflicting Debian-native packages BEFORE the apt install, per
    Docker's official 'Uninstall old versions' prerequisite step.
    """
    text = BOOTSTRAP.read_text()
    lines = text.splitlines()

    # Must name every known-conflicting Debian-native docker package.
    required_packages = [
        "docker.io",
        "docker-buildx",
        "docker-compose",
    ]
    for pkg in required_packages:
        assert pkg in text, (
            f"bootstrap.sh must reference `{pkg}` in its "
            f"conflict-purge block (Trixie file-conflict fix)"
        )

    # Helper: treat a line as code only if the apt keyword is not preceded
    # by a `#` on that line (avoids matching inside comments).
    def _is_code(line: str, keyword: str) -> bool:
        m = re.search(rf"apt(-get)?\s+{keyword}\b", line)
        if not m:
            return False
        before = line[: m.start()]
        return "#" not in before

    purge_idx = next(
        (i for i, line in enumerate(lines) if _is_code(line, "remove")),
        None,
    )
    assert purge_idx is not None, (
        "bootstrap.sh must contain an `apt remove` step that purges "
        "Debian-native docker-buildx / docker-compose / docker.io "
        "BEFORE the docker-ce install. None found."
    )

    # docker-ce may be on a continuation line: find first real `apt install`
    # whose 6-line window contains `docker-ce`.
    install_idx = None
    for i, line in enumerate(lines):
        if _is_code(line, "install"):
            window = "\n".join(lines[i:i + 6])
            if "docker-ce" in window:
                install_idx = i
                break
    assert install_idx is not None, "could not locate `apt install` for docker-ce"

    assert purge_idx < install_idx, (
        f"purge step at line {purge_idx + 1} must come BEFORE the "
        f"`apt install docker-ce` at line {install_idx + 1}. "
        f"Purging after install cannot help — dpkg has already aborted."
    )


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
