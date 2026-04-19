"""Regression test: setup/requirements.txt must pin websockets.

Background (2026-04-19 NIGHT beta report): every beta tester who clicked
"Start Pipeline" hit an apparently frozen wizard. The pipeline runs in
the background but the wizard's progress pane never updates. Root cause:
`setup/requirements.txt` lists `uvicorn` (not `uvicorn[standard]`) and
no explicit `websockets`. FastAPI's @app.websocket("/ws/progress")
endpoint in setup/main.py:588 tries to upgrade the connection; uvicorn's
`auto` WebSocket protocol resolves to nothing because neither `websockets`
nor `wsproto` is installed; every client handshake fails.

The frontend at setup/static/setup.js:802 retries silently forever with
no UI banner. Beta tester sees a frozen wizard. Background error is
not surfaced. Not caught by the LXD smoke harness, which exits before
clicking "Start Pipeline" and thus never opens a WebSocket.

This test is a cheap static guard. If the line goes missing, CI fails
before the harness even runs. Pairs with the harness assertion that
actually connects to the WebSocket end-to-end.
"""
from pathlib import Path
import re

REQS = Path(__file__).parent.parent / "setup" / "requirements.txt"


def test_setup_requirements_pins_websockets():
    text = REQS.read_text()
    # Accept either an explicit `websockets` line OR `uvicorn[standard]`
    # (which pulls in websockets as an extra). Both satisfy the runtime
    # constraint and catch the bug class; prefer the explicit pin for
    # smaller surface.
    explicit = any(
        re.match(r"^\s*websockets\b", line)
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )
    uvicorn_standard = any(
        re.match(r"^\s*uvicorn\s*\[\s*standard\s*\]", line)
        for line in text.splitlines()
        if not line.lstrip().startswith("#")
    )
    assert explicit or uvicorn_standard, (
        "setup/requirements.txt must declare `websockets` (or "
        "`uvicorn[standard]` which includes it). Otherwise FastAPI's "
        "/ws/progress endpoint silently fails every handshake and the "
        "beta tester sees a frozen wizard."
    )


def test_setup_main_still_uses_websocket_endpoint():
    """Canary — if setup/main.py stops using @app.websocket, the
    requirement above can be relaxed. Until then it's load-bearing."""
    main_py = Path(__file__).parent.parent / "setup" / "main.py"
    text = main_py.read_text()
    assert "@app.websocket" in text, (
        "setup/main.py no longer uses @app.websocket — if you removed "
        "the progress stream, this test (and the websockets pin) can "
        "go away. If you didn't mean to remove it, restore the endpoint."
    )
