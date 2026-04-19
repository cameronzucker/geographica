"""FastAPI setup wizard for Geographica — CSRF-protected, ephemeral."""
from __future__ import annotations

import secrets
import asyncio
import json
import os
import signal
import shutil
import subprocess
import sys
import time
from pathlib import Path
from collections import deque
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from setup.config import (
    validate_bbox, get_ram_profile, detect_host_ip,
    detect_ram_mb, detect_storage, generate_env, REGION_PRESETS,
    validate_path, ALLOWED_PATH_PREFIXES,
)
from setup.runner import Checkpoint, run_command, shutdown_children
from setup.pipeline_steps import ALL_PIPELINE_STEPS, filter_active_steps

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CSRF token — generated once at startup
CSRF_TOKEN = secrets.token_hex(32)

# ---------------------------------------------------------------------------
# Preflight helper functions
# ---------------------------------------------------------------------------

def _check_python_pipeline_deps() -> dict:
    """Verify rasterio/shapely/scipy/numpy importable."""
    missing = []
    for pkg in ("rasterio", "shapely", "scipy", "numpy"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        return {"status": "missing", "message": f"Missing: {', '.join(missing)}",
                "fix_hint": "Run: sudo ./bootstrap.sh (installs scripts/requirements.txt)"}
    return {"status": "ok", "message": "rasterio, shapely, scipy, numpy all importable"}


async def _check_keyring_socket() -> dict:
    """Verify keyring agent responds on Unix socket."""
    try:
        reader, writer = await asyncio.open_unix_connection("/run/geographica/keyring.sock")
        writer.write(b'{"action":"ping"}\n')
        await writer.drain()
        await asyncio.wait_for(reader.readline(), timeout=2.0)
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
        return {"status": "ok", "message": "keyring agent responsive"}
    except Exception as e:
        return {"status": "error", "message": f"Keyring unreachable: {e}",
                "fix_hint": "Run: sudo systemctl start geographica-keyring"}


def _check_cgroup_memory() -> dict:
    """Verify Docker has cgroup memory limit support."""
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=5)
        combined = (proc.stdout or "") + (proc.stderr or "")
        if "No memory limit support" in combined or "WARNING: No memory limit support" in combined:
            return {"status": "error",
                    "message": "Docker cgroup memory support disabled",
                    "fix_hint": "Run: sudo ./bootstrap.sh then reboot (edits /boot/firmware/cmdline.txt)"}
        return {"status": "ok", "message": "cgroup memory limits supported"}
    except Exception as e:
        return {"status": "error", "message": f"docker info failed: {e}",
                "fix_hint": "Verify Docker is running: sudo systemctl start docker"}


# Preflight dependency checks — command to run and what constitutes success
PREFLIGHT_CHECKS: list[dict] = [
    {"name": "docker", "check_cmd": ["docker", "--version"], "label": "Docker",
     "fix_hint": "Run: sudo ./bootstrap.sh (installs docker-ce)"},
    {"name": "docker-compose", "check_cmd": ["docker", "compose", "version"], "label": "Docker Compose",
     "fix_hint": "Run: sudo ./bootstrap.sh (installs docker-compose-plugin)"},
    {"name": "python3", "check_cmd": ["python3", "--version"], "label": "Python 3",
     "fix_hint": "Run: sudo ./bootstrap.sh"},
    {"name": "gdal-bin", "check_cmd": ["gdalinfo", "--version"], "label": "GDAL",
     "fix_hint": "Run: sudo ./bootstrap.sh (installs gdal-bin)"},
    {"name": "osmium-tool", "check_cmd": ["osmium", "--version"], "label": "Osmium Tool",
     "fix_hint": "Run: sudo ./bootstrap.sh (installs osmium-tool)"},
    {"name": "gpsd", "check_cmd": ["gpsd", "-V"], "label": "GPSD",
     "fix_hint": "Run: sudo ./bootstrap.sh"},
    {"name": "wget", "check_cmd": ["wget", "--version"], "label": "wget",
     "fix_hint": "Run: sudo ./bootstrap.sh"},
    {"name": "curl", "check_cmd": ["curl", "--version"], "label": "curl",
     "fix_hint": "Run: sudo ./bootstrap.sh"},
    {"name": "git", "check_cmd": ["git", "--version"], "label": "Git",
     "fix_hint": "Run: sudo ./bootstrap.sh"},
    {"name": "tippecanoe", "check_cmd": ["tippecanoe", "--version"], "label": "Tippecanoe",
     "fix_hint": "Run: sudo ./bootstrap.sh (installs tippecanoe 2.79.0 from GitHub Release)"},
    {"name": "openssl", "check_cmd": ["openssl", "version"], "label": "OpenSSL",
     "fix_hint": "Run: sudo ./bootstrap.sh"},
    {"name": "python-pipeline-deps", "label": "Python pipeline deps (rasterio/shapely/scipy/numpy)",
     "check_fn": _check_python_pipeline_deps,
     "fix_hint": "Run: sudo ./bootstrap.sh (installs scripts/requirements.txt)"},
    {"name": "keyring-agent", "label": "Keyring agent (credential storage)",
     "check_fn": _check_keyring_socket,
     "fix_hint": "Run: sudo systemctl start geographica-keyring"},
    {"name": "cgroup-memory", "label": "Docker cgroup memory support",
     "check_fn": _check_cgroup_memory,
     "fix_hint": "Run: sudo ./bootstrap.sh then reboot"},
]

# Keyring agent Unix socket — installed by bootstrap's keyring-agent step
KEYRING_SOCKET_PATH = "/run/geographica/keyring.sock"

# Static files directory
STATIC_DIR = str(Path(__file__).parent / "static")

# .env file path
ENV_PATH = str(Path(__file__).parent.parent / ".env")

# Inactivity timeout (seconds)
INACTIVITY_TIMEOUT = 30 * 60

# ---------------------------------------------------------------------------
# Progress state for WebSocket reconnect
# ---------------------------------------------------------------------------
progress_buffer: deque = deque(maxlen=100)
current_state: dict = {"step": "idle", "substep": None, "progress_pct": 0, "running": False}
connected_websockets: list[WebSocket] = []

# Lock guarding current_state["running"] — prevents TOCTOU on /api/start
_start_lock = asyncio.Lock()

# Track last activity
_last_activity: float = time.time()

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI()

# CORS — localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8099"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# CSRF middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """Check X-CSRF-Token header on POST/PUT/DELETE requests."""
    global _last_activity
    _last_activity = time.time()

    if request.method in ("POST", "PUT", "DELETE"):
        token = request.headers.get("X-CSRF-Token")
        if not token or token != CSRF_TOKEN:
            return JSONResponse(status_code=403, content={"detail": "CSRF token missing or invalid"})

    response = await call_next(request)
    return response


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------
class BboxRequest(BaseModel):
    bbox: str


class ConfigRequest(BaseModel):
    tls_mode: str
    bbox: str
    data_path: str
    scripts_path: str = ""
    tls_cert_dir: str = "./tls"
    tls_port: int = 443
    stt_backend: str = "cpu"


class CredentialsRequest(BaseModel):
    m2m_username: str = ""
    m2m_token: str = ""
    copernicus_username: str = ""
    copernicus_password: str = ""


class PathRequest(BaseModel):
    path: str


class CreateDirectoryRequest(BaseModel):
    path: str


class CheckpointResetRequest(BaseModel):
    data_path: str


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bbox: str
    layers: dict = {}  # {basemap, base_imagery, detail_imagery, elevation} -> source|'skip'
    data_path: str = "/srv/geographica/data"
    base_imagery_zoom: int = 15
    layer_bbox: dict = {}  # {layer: bbox_string} — empty string means "same as top-level bbox"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/")
async def index():
    """Serve index.html with CSRF token injected."""
    index_path = Path(STATIC_DIR) / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="index.html not found")
    html = index_path.read_text()
    html = html.replace("PLACEHOLDER", CSRF_TOKEN)
    return HTMLResponse(content=html)


@app.get("/api/system")
async def get_system():
    """Return system detection info."""
    ram_mb = detect_ram_mb()
    return {
        "host_ip": detect_host_ip(),
        "ram_mb": ram_mb,
        "ram_profile": get_ram_profile(ram_mb),
        "storage": detect_storage(),
        "existing_env": os.path.exists(ENV_PATH),
    }


@app.get("/api/presets")
async def get_presets():
    """Return region presets."""
    return REGION_PRESETS


@app.post("/api/validate-bbox")
async def post_validate_bbox(body: BboxRequest):
    """Validate a bounding box string."""
    return {"valid": validate_bbox(body.bbox)}


@app.post("/api/validate-path")
async def post_validate_path(body: PathRequest):
    """Validate a filesystem path against the ALLOWLIST."""
    return validate_path(body.path)


@app.get("/api/preflight")
async def get_preflight():
    """Run preflight dependency checks."""
    results = []
    for entry in PREFLIGHT_CHECKS:
        name = entry["name"]
        label = entry.get("label", name)
        fix_hint = entry.get("fix_hint", "")
        if "check_fn" in entry:
            fn = entry["check_fn"]
            if asyncio.iscoroutinefunction(fn):
                check_result = await fn()
            else:
                check_result = fn()
        else:
            cmd = entry["check_cmd"]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if proc.returncode == 0:
                    first_line = (proc.stdout or proc.stderr).strip().splitlines()[0:1]
                    msg = first_line[0] if first_line else "ok"
                    check_result = {"status": "ok", "message": msg}
                else:
                    check_result = {"status": "missing",
                                    "message": (proc.stderr or proc.stdout or "").strip()[:200]}
            except FileNotFoundError:
                check_result = {"status": "missing", "message": f"{cmd[0]} not on PATH"}
            except subprocess.TimeoutExpired:
                check_result = {"status": "error", "message": "timeout"}
            except Exception as e:
                check_result = {"status": "error", "message": str(e)[:200]}
        result = {
            "name": name,
            "label": label,
            "status": check_result.get("status", "error"),
            "message": check_result.get("message", ""),
            "fix_hint": check_result.get("fix_hint", fix_hint),
        }
        results.append(result)
    return {"checks": results}


@app.post("/api/create-directory")
async def post_create_directory(body: CreateDirectoryRequest):
    """Create a directory at the specified path.

    SECURITY: Path must pass validate_path (ALLOWLIST check).
    """
    validation = validate_path(body.path)
    if not validation.get("valid"):
        raise HTTPException(
            status_code=400,
            detail=validation.get("reason", "Invalid path"),
        )

    try:
        Path(body.path).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "path": body.path}
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"Cannot create directory: {e}")


@app.post("/api/config")
async def post_config(body: ConfigRequest):
    """Generate and write .env file."""
    ALLOWED_TLS_MODES = {"http", "https", "tailscale"}
    if body.tls_mode not in ALLOWED_TLS_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"tls_mode must be one of {sorted(ALLOWED_TLS_MODES)}"
        )
    if not validate_bbox(body.bbox):
        raise HTTPException(status_code=400, detail="Invalid bbox")
    scripts_path = body.scripts_path or str(Path(__file__).parent.parent / "scripts")
    ram_mb = detect_ram_mb()
    ram_profile = get_ram_profile(ram_mb)
    env_content = generate_env(
        tls_mode=body.tls_mode,
        bbox=body.bbox,
        data_path=body.data_path,
        scripts_path=scripts_path,
        ram_profile=ram_profile,
        tls_cert_dir=body.tls_cert_dir,
        tls_port=body.tls_port,
        stt_backend=body.stt_backend,
    )
    Path(ENV_PATH).write_text(env_content)
    return {"ok": True}


async def _store_one(cred_type: str, key: str, value: str) -> None:
    """Send a single store-action to the keyring agent (one connection per request).

    Matches the agent's one-request-per-connection protocol (services/keyring-agent/agent.py)
    and mirrors the canonical sync client at services/search/keyring_client.py::_request.

    Raises HTTPException(503) if the socket is unavailable (actionable: points at
    systemctl). Raises HTTPException(500) if the agent responds with ok=False or
    closes unexpectedly.
    """
    try:
        reader, writer = await asyncio.open_unix_connection(KEYRING_SOCKET_PATH)
    except (FileNotFoundError, ConnectionRefusedError) as e:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Keyring agent not reachable at {KEYRING_SOCKET_PATH} ({e}). "
                "Open a terminal and run: sudo systemctl start geographica-keyring"
            ),
        )
    try:
        msg = json.dumps({
            "action": "store",
            "type": cred_type,
            "key": key,
            "value": value,
        }) + "\n"
        writer.write(msg.encode("utf-8"))
        await writer.drain()
        resp_line = await reader.readline()
        if not resp_line:
            raise HTTPException(
                status_code=500,
                detail=f"keyring agent closed socket without responding ({cred_type}/{key})",
            )
        try:
            resp = json.loads(resp_line.decode("utf-8"))
        except json.JSONDecodeError as err:
            raise HTTPException(
                status_code=500,
                detail=f"keyring agent returned invalid JSON ({cred_type}/{key}): {err}",
            )
        if not resp.get("ok"):
            raise HTTPException(
                status_code=500,
                detail=f"keyring agent rejected {cred_type}/{key}: {resp.get('error', 'unknown')}",
            )
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass


async def _write_to_keyring(cred_type: str, fields: dict[str, str]) -> None:
    """Store each non-empty field with one-connection-per-store.

    Empty values are skipped so partial form fills don't clobber previously
    stored entries.
    """
    for key, value in fields.items():
        if not value:
            continue
        await _store_one(cred_type, key, value)


@app.post("/api/credentials")
async def post_credentials(body: CredentialsRequest):
    await _write_to_keyring("m2m", {
        "username": body.m2m_username,
        "token": body.m2m_token,
    })
    await _write_to_keyring("copernicus", {
        "username": body.copernicus_username,
        "password": body.copernicus_password,
    })
    return {"ok": True}


@app.get("/api/status")
async def get_status():
    """Return current pipeline state."""
    return current_state


@app.get("/api/health")
async def get_health():
    """Check Docker Compose service health."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", "ps", "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(__file__).parent.parent),
        )
        stdout, _ = await proc.communicate()
        text = stdout.decode("utf-8", errors="replace").strip()
        services = []
        if text:
            for line in text.splitlines():
                try:
                    services.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"services": services}
    except Exception as e:
        return {"services": [], "error": str(e)}


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws/progress")
async def ws_progress(websocket: WebSocket):
    """Stream progress events to connected clients."""
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        # Send buffered events on connect — snapshot to avoid deque-mutated-during-iteration
        for event in list(progress_buffer):
            await websocket.send_json(event)
        await websocket.send_json(current_state)
        # Keep alive, waiting for disconnect
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


async def broadcast(event: dict):
    """Broadcast event to all connected WebSockets in parallel with per-socket timeout.

    Hanging sockets are dropped after 2s so they can't stall the pipeline.
    """
    progress_buffer.append(event)
    socks = list(connected_websockets)
    if not socks:
        return
    async def _send(ws):
        try:
            await asyncio.wait_for(ws.send_json(event), timeout=2.0)
            return None
        except Exception:
            return ws
    results = await asyncio.gather(*[_send(w) for w in socks], return_exceptions=True)
    for r in results:
        if r is None or isinstance(r, Exception):
            continue
        # `_send` returns the failing ws to drop. We compare identity to ws objects.
        if r in connected_websockets:
            connected_websockets.remove(r)


@app.post("/api/start")
async def post_start(body: StartRequest):
    """Start the download/build pipeline as a background task."""
    if not validate_bbox(body.bbox):
        raise HTTPException(status_code=400, detail="Invalid bbox")
    async with _start_lock:
        if current_state["running"]:
            raise HTTPException(status_code=409, detail="Pipeline already running")
        current_state["running"] = True
        current_state["step"] = "starting"
    asyncio.create_task(_run_pipeline(body))
    return {"ok": True, "steps": [s.id for s in ALL_PIPELINE_STEPS]}


async def _run_pipeline(config: "StartRequest") -> None:
    """Run each active pipeline step in sequence. Every branch clears running=False."""
    cwd = str(Path(__file__).parent.parent)
    ctx: dict = {
        "bbox": config.bbox,
        "layer_bbox": config.layer_bbox or {},
        "layers": config.layers or {},
        "data_path": config.data_path,
        "scripts_path": str(Path(cwd) / "scripts"),
        "base_imagery_zoom": config.base_imagery_zoom,
    }
    ckpt_path = Path(config.data_path) / ".setup_checkpoint.json"
    checkpoint = Checkpoint(str(ckpt_path))

    current_state["step"] = "running"

    def make_on_output(step_id: str):
        """Produce a 2-arg callback matching run_command's contract:
            on_output(source: str, data: bytes) -> None"""
        def _on_output(source: str, data: bytes) -> None:
            text = data.decode("utf-8", errors="replace")
            asyncio.create_task(broadcast({
                "type": "output",
                "step": step_id,
                "source": source,
                "data": text,
            }))
        return _on_output

    try:
        active = filter_active_steps(ALL_PIPELINE_STEPS, ctx["layers"])
        for step in active:
            if checkpoint.is_completed(step.id):
                await broadcast({"type": "step_skipped", "step": step.id,
                                 "reason": "checkpoint"})
                continue

            await broadcast({"type": "step_start", "step": step.id,
                             "label": step.label})

            try:
                usage = shutil.disk_usage(config.data_path)
                free_gb = usage.free / (1024 ** 3)
            except FileNotFoundError:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": f"Data path {config.data_path} does not exist. "
                               "Create it or rerun Step 1.",
                })
                return
            if free_gb < 5:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": f"Only {free_gb:.1f} GB free at {config.data_path}; "
                               "need at least 5 GB to continue.",
                })
                return

            try:
                cmd = step.cmd_builder(ctx)
            except Exception as e:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": f"cmd builder failed: {e!r}",
                })
                return

            stderr_tail = bytearray()
            step_output_cb = make_on_output(step.id)

            def _step_on_output(source: str, data: bytes):
                if source == "stderr":
                    stderr_tail.extend(data)
                    if len(stderr_tail) > 2000:
                        del stderr_tail[:len(stderr_tail) - 2000]
                step_output_cb(source, data)

            exit_code = await run_command(args=cmd, cwd=cwd, on_output=_step_on_output)
            if exit_code != 0:
                current_state["step"] = "error"
                await broadcast({
                    "type": "error", "step": step.id,
                    "message": stderr_tail[-500:].decode("utf-8", errors="replace") or
                               f"exit code {exit_code} (no stderr captured)",
                })
                return

            checkpoint.mark_completed(step.id)
            await broadcast({"type": "step_done", "step": step.id})

        current_state["step"] = "done"
        await broadcast({"type": "pipeline_done"})
    except Exception as e:
        current_state["step"] = "error"
        await broadcast({
            "type": "error",
            "message": f"Unhandled pipeline error: {e!r}",
        })
    finally:
        current_state["running"] = False
        await broadcast({"type": "state", "running": False,
                         "step": current_state["step"]})


# ---------------------------------------------------------------------------
# Checkpoint reset
# ---------------------------------------------------------------------------
@app.post("/api/checkpoint/reset")
async def post_checkpoint_reset(body: CheckpointResetRequest):
    validation = validate_path(body.data_path)
    if not validation.get("valid"):
        raise HTTPException(status_code=400, detail=validation.get("reason", "Invalid path"))
    ckpt_path = Path(body.data_path) / ".setup_checkpoint.json"
    if ckpt_path.exists():
        try:
            ckpt_path.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"Could not delete checkpoint: {e}")
    return {"ok": True}


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
@app.post("/api/launch")
async def post_launch():
    """Launch Docker Compose stack. Detects existing containers."""
    cwd = str(Path(__file__).parent.parent)

    # Re-target ./data symlink to match DATA_HOST_PATH in .env (B2).
    # The wizard writes DATA_HOST_PATH to .env; bootstrap originally created
    # ./data → /srv/geographica/data, but users can choose a different drive
    # in Step 1. Reconcile them here, right before we hand off to docker-compose.
    try:
        env_text = Path(ENV_PATH).read_text() if Path(ENV_PATH).exists() else ""
    except OSError:
        env_text = ""
    data_host_path: Optional[str] = None
    for line in env_text.splitlines():
        line = line.strip()
        if line.startswith("DATA_HOST_PATH="):
            raw = line.split("=", 1)[1].strip()
            # Strip surrounding quotes if present.
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
                raw = raw[1:-1]
            data_host_path = raw
            break
    if data_host_path:
        target = Path(data_host_path)
        data_link = Path.cwd() / "data"
        current_target = None
        if data_link.is_symlink():
            try:
                current_target = data_link.resolve()
            except OSError:
                current_target = None
        if current_target is None or current_target != target.resolve():
            try:
                target.mkdir(parents=True, exist_ok=True)
                if data_link.exists() or data_link.is_symlink():
                    if data_link.is_symlink():
                        data_link.unlink()
                    elif data_link.is_dir():
                        raise HTTPException(
                            status_code=400,
                            detail=(
                                f"{data_link} is a regular directory, not a symlink. "
                                "Move or remove it manually before re-launching."
                            ),
                        )
                    else:
                        raise HTTPException(
                            status_code=400,
                            detail=f"{data_link} exists and is not a symlink — move it manually.",
                        )
                data_link.symlink_to(target)
            except HTTPException:
                raise
            except OSError as err:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to retarget ./data symlink to {target}: {err}",
                )

    # Check if containers are already running
    pre_check = await asyncio.create_subprocess_exec(
        "docker", "compose", "ps", "--format", "json",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    pre_stdout, _ = await pre_check.communicate()
    pre_text = pre_stdout.decode("utf-8", errors="replace").strip()

    existing_services = []
    if pre_text:
        for line in pre_text.splitlines():
            try:
                svc = json.loads(line)
                existing_services.append(svc)
            except json.JSONDecodeError:
                continue

    already_running = len(existing_services) > 0
    all_healthy = all(
        "healthy" in (s.get("Health", "") or s.get("Status", ""))
        for s in existing_services
    ) if existing_services else False

    # Run docker compose up -d
    output_lines: list[str] = []

    def on_output(source: str, data: bytes):
        output_lines.append(data.decode("utf-8", errors="replace"))

    exit_code = await run_command(
        args=["docker", "compose", "-f", "docker-compose.yml", "up", "-d"],
        cwd=cwd,
        on_output=on_output,
    )

    # Determine launch state
    if already_running and all_healthy:
        state = "already_healthy"
    elif already_running:
        state = "restarted"
    else:
        state = "started"

    return {
        "exit_code": exit_code,
        "output": "".join(output_lines),
        "state": state,
        "existing_count": len(existing_services),
    }


# ---------------------------------------------------------------------------
# SIGTERM handler
# ---------------------------------------------------------------------------
def _handle_sigterm(signum, frame):
    shutdown_children()
    sys.exit(0)


signal.signal(signal.SIGTERM, _handle_sigterm)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8099)
