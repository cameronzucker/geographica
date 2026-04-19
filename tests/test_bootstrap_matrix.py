"""Pre-state matrix for bootstrap.sh — static guards.

The matrix itself is an integration test (`dev/harness/bootstrap-matrix.sh`)
that runs ephemeral Docker Trixie containers to prove bootstrap survives
customer-realistic starting states. These unit tests are a fast canary that
the matrix files exist, are syntactically valid, and cover the bug class
that blocked every beta tester on 2026-04-19 (Debian-native docker-buildx
and docker-compose packages file-conflicting with Docker's official plugins).

If these tests fail, the bootstrap pre-state matrix has been removed or
damaged — future regressions in bootstrap will ship to beta testers
without CI catching them.
"""
import subprocess
from pathlib import Path

HARNESS_DIR = Path(__file__).parent.parent / "dev" / "harness"
MATRIX_SCRIPT = HARNESS_DIR / "bootstrap-matrix.sh"
PRE_STATES_DIR = HARNESS_DIR / "pre-states"


REQUIRED_PRE_STATES = [
    # baseline: no pre-installed docker anything
    "clean.sh",
    # THE critical beta reproducer: Debian's docker-buildx + docker-compose
    # physically collide with Docker's -plugin packages. Every beta tester
    # who had ever run `apt install docker.io` or done a full-upgrade with
    # docker.io installed hit this.
    "debian-docker-buildx.sh",
    # legacy path: docker.io is the Debian 12 (bookworm) default Docker
    # package. On Trixie it pulls in the conflicting docker-buildx+compose
    # as recommends.
    "docker-io.sh",
    # user followed https://get.docker.com before running bootstrap — leaves
    # docker.asc keyring + docker-ce + plugins already installed. The
    # repo-setup guard must not double-register and apt must not re-download.
    "get-docker-com.sh",
]


def test_matrix_runner_exists_and_is_executable():
    assert MATRIX_SCRIPT.exists(), f"missing {MATRIX_SCRIPT}"
    mode = MATRIX_SCRIPT.stat().st_mode
    assert mode & 0o111, f"{MATRIX_SCRIPT} is not executable"


def test_matrix_runner_is_valid_bash():
    result = subprocess.run(
        ["bash", "-n", str(MATRIX_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bash -n failed on {MATRIX_SCRIPT}:\n{result.stderr}"
    )


def test_pre_states_dir_exists():
    assert PRE_STATES_DIR.is_dir(), f"missing {PRE_STATES_DIR}"


def test_every_required_pre_state_exists():
    for name in REQUIRED_PRE_STATES:
        path = PRE_STATES_DIR / name
        assert path.exists(), f"missing pre-state: {path}"


def test_every_pre_state_is_valid_bash():
    for path in sorted(PRE_STATES_DIR.glob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", str(path)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"bash -n failed on {path}:\n{result.stderr}"
        )


def test_matrix_runner_discovers_every_required_pre_state():
    """Behavioral check: `bootstrap-matrix.sh --help` must list each
    required pre-state as available. The runner is designed to glob
    the pre-states directory, so this asserts the glob + directory
    contract wire together correctly."""
    result = subprocess.run(
        [str(MATRIX_SCRIPT), "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"--help should exit 0, got {result.returncode}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    for name in REQUIRED_PRE_STATES:
        stem = name.rsplit(".", 1)[0]
        assert stem in result.stdout, (
            f"pre-state '{stem}' is not discovered by the runner --help listing.\n"
            f"--help output was:\n{result.stdout}"
        )


def test_critical_beta_reproducer_installs_debian_docker_buildx():
    """The `debian-docker-buildx` pre-state is the exact 2026-04-19 beta
    failure. It MUST install Debian's docker-buildx (and ideally
    docker-compose too) — otherwise the matrix would not catch this bug."""
    path = PRE_STATES_DIR / "debian-docker-buildx.sh"
    text = path.read_text()
    assert "docker-buildx" in text, (
        "critical beta pre-state must install docker-buildx to reproduce"
    )
    # This pre-state also exercises the docker-compose leg, which shares
    # the same failure mode.
    assert "docker-compose" in text


def test_matrix_fails_fast_on_first_pre_state_failure():
    """CI must exit non-zero if any pre-state fails, not march onward
    and paper over regressions. `set -e` in the runner is the signal."""
    runner_text = MATRIX_SCRIPT.read_text().splitlines()
    # Look for `set -e` or equivalent within the first 10 non-blank,
    # non-comment lines.
    header_lines = [
        line.strip() for line in runner_text[:30]
        if line.strip() and not line.strip().startswith("#")
    ][:10]
    header_text = "\n".join(header_lines)
    assert (
        "set -e" in header_text
        or "set -eu" in header_text
        or "set -euo" in header_text
    ), "bootstrap-matrix.sh must use `set -e` so a failed pre-state fails CI"
