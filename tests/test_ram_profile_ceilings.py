"""Two-tier memory-ceiling tests.

Enforces that default RAM profiles fit a 'good neighbor' contract:
Geographica's always-on services claim <= 62% (16GB) / 50% (8GB) of host RAM
by default, leaving room for the host kernel, page cache, and other services
the user may run on the same Pi.

Users can override any specific service's memory via .env to reclaim
headroom on a dedicated Pi.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "setup"))

from config import RAM_PROFILE_16GB, RAM_PROFILE_8GB


def _to_mb(value: str) -> int:
    """Parse a Docker/JVM-style memory string (e.g. '1G', '512M', '1536MB', '3g') to MB."""
    m = re.match(r"^(\d+)([A-Za-z]+)$", value.strip())
    if not m:
        raise ValueError(f"Unparseable memory value: {value!r}")
    n, unit = m.groups()
    unit = unit.upper()
    multipliers = {"M": 1, "MB": 1, "G": 1024, "GB": 1024}
    if unit not in multipliers:
        raise ValueError(f"Unknown memory unit: {unit!r} in {value!r}")
    return int(n) * multipliers[unit]


def _always_on_mb(profile: dict) -> int:
    """Sum of always-running service memory limits: nominatim + valhalla + tileserver + stt."""
    return sum(_to_mb(profile[k]) for k in (
        "nominatim_memory",
        "valhalla_memory",
        "tileserver_memory",
        "stt_memory",
    ))


def _peak_mb(profile: dict) -> int:
    """Always-on + pipeline (worst-case simultaneous peak)."""
    return _always_on_mb(profile) + _to_mb(profile["pipeline_memory"])


class TestProfile16GBCeiling:
    def test_always_on_fits_shared_host(self):
        """16GB profile leaves >=6 GB for host/kernel/user's other services."""
        total = _always_on_mb(RAM_PROFILE_16GB)
        assert total <= 10 * 1024, (
            f"16GB profile always-on sum is {total} MB (cap 10240 MB / 10 GB). "
            "This leaves too little room for a host running other services alongside Geographica. "
            "Either tighten per-service memory limits or update the ceiling framework in the "
            "implementation-log."
        )

    def test_peak_under_pi_ram(self):
        """16GB profile peak (pipeline running) leaves >=3 GB host headroom."""
        peak = _peak_mb(RAM_PROFILE_16GB)
        assert peak <= 13 * 1024, (
            f"16GB profile peak (always-on + pipeline) is {peak} MB (cap 13312 MB / 13 GB)."
        )


class TestProfile8GBCeiling:
    def test_always_on_fits_shared_host(self):
        """8GB profile leaves >=4 GB for host/kernel/user's other services."""
        total = _always_on_mb(RAM_PROFILE_8GB)
        assert total <= 4 * 1024, (
            f"8GB profile always-on sum is {total} MB (cap 4096 MB / 4 GB)."
        )

    def test_peak_under_pi_ram(self):
        """8GB profile peak leaves >=2 GB host headroom."""
        peak = _peak_mb(RAM_PROFILE_8GB)
        assert peak <= 6 * 1024, (
            f"8GB profile peak (always-on + pipeline) is {peak} MB (cap 6144 MB / 6 GB)."
        )
