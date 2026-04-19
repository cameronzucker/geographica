import re
from pathlib import Path
COMPOSE = Path(__file__).parent.parent / "docker-compose.yml"


def test_memory_limits_are_env_parameterized():
    text = COMPOSE.read_text()
    pattern = re.compile(r"^\s*memory:\s*(?!\"?\$\{)(\S+)", re.MULTILINE)
    bad = pattern.findall(text)
    allowed_fixed = {"128M", "256M"}
    unexpected = [b for b in bad if b not in allowed_fixed]
    assert not unexpected, f"hard-coded memory limits: {unexpected}"


def test_required_vars_present():
    text = COMPOSE.read_text()
    for var in ("${TILESERVER_MEMORY", "${VALHALLA_MEMORY", "${NOMINATIM_MEMORY",
                "${STT_MEMORY", "${PIPELINE_MEMORY"):
        assert var in text
