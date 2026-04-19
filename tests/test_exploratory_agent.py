"""Unit tests for dev/harness/exploratory_agent/.

All tests mock Playwright, the Anthropic SDK, and `lxc exec`. No real
containers. No real API calls. Runs in under 5 seconds.

The integration test (against a real LXD container) lives in
dev/harness/wizard-ci.sh --exploratory and is gated behind
ANTHROPIC_API_KEY; it is not part of this pytest suite.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_package_importable():
    import dev.harness.exploratory_agent as pkg
    assert pkg is not None
