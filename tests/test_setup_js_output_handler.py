"""Regression test for setup.js's WebSocket `output` event handler.

2026-04-20 beta-tester screenshot showed the log viewer filled with
`undefinedundefinedundefinedundefined...` burying the real
`Exception: data/sources/lake_centerline.shp.zip does not exist`
message.

Root cause: the backend at setup/main.py::_on_output broadcasts
`{type: "output", data: <text>, source, step}`. The frontend at
setup/static/setup.js read `event.text` (which was never set), so
`appendLog(undefined)` stringified "undefined" into the pre for every
chunk of subprocess stdout/stderr — thousands of times per step on a
verbose tool like Planetiler.

This file guards two invariants:

  1. setup.js's output handler reads event.data (not event.text).
  2. setup/main.py's broadcast still emits `data` as the field name
     (so the frontend's fallback doesn't silently paper over a
     backend-side rename).

Static-grep tests; no browser or Python runtime needed.
"""
from pathlib import Path
import re


SETUP_JS = Path(__file__).parent.parent / "setup" / "static" / "setup.js"
SETUP_MAIN = Path(__file__).parent.parent / "setup" / "main.py"


def test_frontend_output_handler_reads_event_data():
    js = SETUP_JS.read_text()
    assert re.search(r"if\s*\(\s*type\s*===\s*['\"]output['\"]", js), \
        "setup.js no longer has a `type === 'output'` handler"
    # The fix fingerprint: appendLog receives event.data (possibly with a
    # fallback). The prior bug was `appendLog(event.text)` where event.text
    # was never set, stringifying "undefined" into the log pane.
    assert re.search(r"appendLog\(\s*event\.data\b", js), (
        "setup.js's 'output' handler must call appendLog(event.data). "
        "The backend broadcasts {type:'output', data:<text>, ...}; "
        "reading event.text would stringify `undefined` into the log "
        "pane for every chunk (2026-04-20 beta-tester symptom)."
    )


def test_frontend_output_handler_does_not_rely_solely_on_event_text():
    """The bug was `appendLog(event.text)` where event.text was never set.
    The fix must not reintroduce that pattern."""
    js = SETUP_JS.read_text()
    # Check there is no line that's literally `appendLog(event.text)`.
    # Allow the fallback `event.data || event.text || ''` form.
    assert "appendLog(event.text)" not in js, (
        "appendLog(event.text) reintroduced; backend sends event.data, "
        "not event.text"
    )


def test_frontend_btn_next_text_refreshes_when_preflight_passes():
    """2026-04-20 beta-tester report: the button on Step 4 read
    `Run Checks` even after preflight went green, which the user
    (reasonably) thought meant clicking it would re-run checks, not
    start the download pipeline. Behaviour is correct (startPipeline()
    reads preflightPassed at click time) but the label is stale
    because it's only set on Step 4 entry (setup.js:124).

    Fix: when preflight's response flips preflightPassed to true,
    also refresh #btn-next.textContent to 'Start Pipeline'."""
    js = SETUP_JS.read_text()
    # Find the "if (allOk) { preflightPassed = true; ... }" block.
    m = re.search(
        r"if\s*\(\s*allOk\s*\)\s*\{([^}]+)\}",
        js,
        re.DOTALL,
    )
    assert m, "setup.js no longer has the `if (allOk)` preflight-passed block"
    block = m.group(1)
    assert "btn-next" in block, (
        "the allOk block must refresh #btn-next.textContent to "
        "'Start Pipeline' so the button label matches the action "
        "once preflight passes"
    )
    assert "Start Pipeline" in block, (
        "the allOk block must set #btn-next text to 'Start Pipeline'"
    )


def test_backend_output_broadcast_still_uses_data_field():
    """Canary — if setup/main.py starts sending a different field,
    this test fails and directs the maintainer to update both sides."""
    py = SETUP_MAIN.read_text()
    # Look for the broadcast dict with type="output".
    m = re.search(
        r'broadcast\s*\(\s*\{\s*[^}]*"type"\s*:\s*"output"[^}]*\}',
        py,
        re.DOTALL,
    )
    assert m, "setup/main.py no longer broadcasts {type:'output', ...}"
    block = m.group(0)
    assert '"data"' in block, (
        "setup/main.py's output broadcast must use 'data' as the text "
        "field name. If you renamed it, update setup.js's output "
        "handler to match (see test_frontend_output_handler_reads_event_data)."
    )
