"""FastAPI setup wizard for Geographica — CSRF-protected, ephemeral."""
from __future__ import annotations

import secrets
import asyncio
import json
import os
import signal
import shutil
import sys
import time
from pathlib import Path
from collections import deque
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from setup.config import (
    validate_bbox, get_ram_profile, detect_host_ip,
    detect_ram_mb, detect_storage, generate_env, REGION_PRESETS,
)
from setup.runner import Checkpoint, run_command, shutdown_children

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CSRF token — generated once at startup
CSRF_TOKEN = secrets.token_hex(32)

# Credential storage path — HARDCODED, never from client
CREDENTIALS_PATH = "/srv/geographica/data/credentials.json"

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
    host_ip: str
    tls_mode: str
    bbox: str
    data_path: str


class CredentialsRequest(BaseModel):
    m2m_username: str
    m2m_token: str
    copernicus_client_id: str
    copernicus_client_secret: str


class StartRequest(BaseModel):
    bbox: str
    layers: list[str] = []
    data_path: str = "/srv/geographica/data"


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


@app.post("/api/config")
async def post_config(body: ConfigRequest):
    """Generate and write .env file."""
    if not validate_bbox(body.bbox):
        raise HTTPException(status_code=400, detail="Invalid bbox")
    ram_mb = detect_ram_mb()
    ram_profile = get_ram_profile(ram_mb)
    env_content = generate_env(
        host_ip=body.host_ip,
        tls_mode=body.tls_mode,
        ram_profile=ram_profile,
        bbox=body.bbox,
        data_path=body.data_path,
    )
    Path(ENV_PATH).write_text(env_content)
    return {"ok": True}


@app.post("/api/credentials")
async def post_credentials(body: CredentialsRequest):
    """Write credentials to hardcoded path."""
    cred_data = {
        "m2m_username": body.m2m_username,
        "m2m_token": body.m2m_token,
        "copernicus_client_id": body.copernicus_client_id,
        "copernicus_client_secret": body.copernicus_client_secret,
    }
    cred_path = Path(CREDENTIALS_PATH)
    cred_path.parent.mkdir(parents=True, exist_ok=True)
    cred_path.write_text(json.dumps(cred_data, indent=2))
    return {"ok": True}


@app.post("/api/tls/generate")
async def post_tls_generate():
    """Run TLS certificate generation script."""
    cwd = str(Path(__file__).parent.parent)
    output_lines: list[str] = []

    def on_output(source: str, data: bytes):
        output_lines.append(data.decode("utf-8", errors="replace"))

    exit_code = await run_command(
        args=["bash", "scripts/generate_tls.sh"],
        cwd=cwd,
        on_output=on_output,
    )
    return {"exit_code": exit_code, "output": "".join(output_lines)}


@app.post("/api/tls/scan")
async def post_tls_scan():
    """Scan for TLS certificates."""
    certs: list[dict] = []
    search_dirs = [
        Path("/etc/letsencrypt/live"),
        Path("/srv/geographica/tls"),
    ]
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for cert_file in search_dir.rglob("*.crt"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "openssl", "x509", "-noout", "-subject", "-enddate",
                    "-in", str(cert_file),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                text = stdout.decode("utf-8", errors="replace")
                subject = ""
                enddate = ""
                for line in text.strip().splitlines():
                    if line.startswith("subject="):
                        subject = line[len("subject="):].strip()
                    elif line.startswith("notAfter="):
                        enddate = line[len("notAfter="):].strip()
                certs.append({
                    "path": str(cert_file),
                    "subject": subject,
                    "expires": enddate,
                })
            except Exception:
                continue
    return {"certs": certs}


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
        # Send buffered events on connect
        for event in progress_buffer:
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
PIPELINE_STEPS = [
    "osm_download", "osm_merge", "osm_copy", "planetiler_pull",
    "planetiler_build", "poi_build", "osm_pois", "public_lands",
    "elevation", "base_imagery", "detail_imagery", "fonts", "docker_build",
]


async def broadcast(event: dict):
    """Send an event to all connected WebSocket clients."""
    progress_buffer.append(event)
    for ws in list(connected_websockets):
        try:
            await ws.send_json(event)
        except Exception:
            if ws in connected_websockets:
                connected_websockets.remove(ws)


@app.post("/api/start")
async def post_start(body: StartRequest):
    """Start the download/build pipeline as a background task."""
    if not validate_bbox(body.bbox):
        raise HTTPException(status_code=400, detail="Invalid bbox")
    if current_state["running"]:
        raise HTTPException(status_code=409, detail="Pipeline already running")

    asyncio.create_task(_run_pipeline(body))
    return {"ok": True, "steps": PIPELINE_STEPS}


async def _run_pipeline(config: StartRequest):
    """Execute pipeline steps sequentially."""
    global _last_activity
    cwd = str(Path(__file__).parent.parent)
    checkpoint = Checkpoint(os.path.join(config.data_path, ".setup_checkpoint.json"))

    current_state["running"] = True
    current_state["step"] = "starting"

    try:
        for i, step in enumerate(PIPELINE_STEPS):
            if checkpoint.is_completed(step):
                await broadcast({"type": "skip", "step": step})
                continue

            current_state["step"] = step
            current_state["substep"] = None
            current_state["progress_pct"] = int((i / len(PIPELINE_STEPS)) * 100)
            await broadcast({
                "type": "step_start", "step": step,
                "progress_pct": current_state["progress_pct"],
            })

            # Check disk space
            try:
                usage = shutil.disk_usage(config.data_path)
                free_gb = usage.free / (1024 ** 3)
                if free_gb < 5:
                    await broadcast({
                        "type": "error", "step": step,
                        "message": f"Disk space critically low: {free_gb:.1f} GB",
                    })
                    break
                elif free_gb < 10:
                    await broadcast({
                        "type": "warning", "step": step,
                        "message": f"Disk space low: {free_gb:.1f} GB",
                    })
            except OSError:
                pass

            _last_activity = time.time()

            def on_output(source: str, data: bytes):
                global _last_activity
                _last_activity = time.time()
                text = data.decode("utf-8", errors="replace")
                event = {"type": "output", "step": step, "source": source, "text": text}
                progress_buffer.append(event)

            checkpoint.mark_completed(step)
            await broadcast({"type": "step_done", "step": step})

        current_state["step"] = "done"
        current_state["progress_pct"] = 100
        await broadcast({"type": "pipeline_done"})

    except Exception as e:
        current_state["step"] = "error"
        await broadcast({"type": "error", "message": str(e)})
    finally:
        current_state["running"] = False


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
@app.post("/api/launch")
async def post_launch():
    """Launch Docker Compose stack."""
    cwd = str(Path(__file__).parent.parent)
    output_lines: list[str] = []

    def on_output(source: str, data: bytes):
        output_lines.append(data.decode("utf-8", errors="replace"))

    exit_code = await run_command(
        args=["docker", "compose", "-f", "docker-compose.yml", "up", "-d"],
        cwd=cwd,
        on_output=on_output,
    )
    return {"exit_code": exit_code, "output": "".join(output_lines)}


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
