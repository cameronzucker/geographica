"""LXD container disruption tools.

The agent uses these to simulate realistic breakage: restarting the
wizard mid-flow (tests CSRF persistence), writing pre-state files,
reading state files, shelling out for arbitrary checks.

SECURITY: container_fs_write refuses paths outside /srv, /tmp, /run.
container_run_command is unrestricted - the LXD container is ephemeral
and deleted at the end of the run. See design spec for rationale.
"""
from __future__ import annotations

import subprocess
from typing import Any

from . import register

_EXEC_TIMEOUT = 30
_STDOUT_MAX = 4_096
_FS_READ_MAX = 8_192
_ALLOWED_WRITE_ROOTS = ("/srv/", "/tmp/", "/run/")

WIZARD_SYSTEMD_UNIT = "geographica-wizard-setup.service"


class ContainerTools:
    def __init__(self, container: str) -> None:
        self.container = container

    def container_run_command_sync(self, command: str) -> dict:
        argv = ["lxc", "exec", self.container, "--", "bash", "-c", command]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"exit": -1, "stdout": "", "stderr": "timeout"}
        return {
            "exit": r.returncode,
            "stdout": r.stdout.decode("utf-8", errors="replace")[:_STDOUT_MAX],
            "stderr": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX],
        }

    def container_restart_wizard_sync(self) -> dict:
        cmd = f"systemctl restart {WIZARD_SYSTEMD_UNIT}"
        argv = ["lxc", "exec", self.container, "--", "bash", "-c", cmd]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        if r.returncode != 0:
            return {"ok": False,
                    "error": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX]}
        return {"ok": True}

    def container_fs_write_sync(self, path: str, content: str) -> dict:
        if not any(path.startswith(r) for r in _ALLOWED_WRITE_ROOTS):
            return {
                "ok": False,
                "error": f"path {path!r} not allowed; must start with one of {_ALLOWED_WRITE_ROOTS}",
            }
        argv = ["lxc", "exec", self.container, "--", "tee", path]
        try:
            r = subprocess.run(argv, input=content.encode("utf-8"),
                               capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        if r.returncode != 0:
            return {"ok": False,
                    "error": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX]}
        return {"ok": True}

    def container_fs_read_sync(self, path: str) -> dict:
        argv = ["lxc", "exec", self.container, "--", "cat", path]
        try:
            r = subprocess.run(argv, capture_output=True, timeout=_EXEC_TIMEOUT)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout"}
        if r.returncode != 0:
            return {"ok": False,
                    "error": r.stderr.decode("utf-8", errors="replace")[:_STDOUT_MAX]}
        return {
            "ok": True,
            "content": r.stdout.decode("utf-8", errors="replace")[:_FS_READ_MAX],
        }


_CONTAINER_SCHEMAS: list[dict] = [
    {
        "name": "container_run_command",
        "description": (
            "Run a shell command inside the LXD container (lxc exec). "
            "stdout/stderr each capped at 4 KB, 30-second timeout."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
    {
        "name": "container_restart_wizard",
        "description": (
            "Restart the setup wizard's systemd unit inside the container. "
            "Simulates `setup.sh` crashing and being relaunched. Useful "
            "for testing CSRF persistence and stale-tab resilience. "
            "Costs ~20 seconds (unit stop + start + uvicorn ready)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "container_fs_write",
        "description": (
            "Write a file inside the container. Path must start with "
            "/srv, /tmp, or /run. Used to seed pre-state for testing."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "container_fs_read",
        "description": "Read a file inside the container. Truncated to 8 KB.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
]


_METHOD_NAMES = {
    "container_run_command": "container_run_command_sync",
    "container_restart_wizard": "container_restart_wizard_sync",
    "container_fs_write": "container_fs_write_sync",
    "container_fs_read": "container_fs_read_sync",
}


def _factory_builder(tool_name: str):
    def factory(ctx):
        return getattr(ctx.container, _METHOD_NAMES[tool_name])
    return factory


for _s in _CONTAINER_SCHEMAS:
    register(_s["name"], _factory_builder(_s["name"]), _s)

from .. import schema as _schema_mod
_schema_mod.TOOL_SCHEMAS.extend(_CONTAINER_SCHEMAS)
