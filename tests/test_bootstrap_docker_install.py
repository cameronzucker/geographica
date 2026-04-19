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
