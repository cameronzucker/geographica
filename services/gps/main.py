"""GPS position streaming service.

Reads from gpsd via gps3 and broadcasts position over WebSocket at 1 Hz.
Stays running even when gpsd is unreachable, returning stale data with fix=0.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
from datetime import datetime, timezone
from math import sqrt
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from gps3 import agps3

logger = logging.getLogger("gps-service")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)

GPSD_HOST = os.environ.get("GPSD_HOST", "localhost")
GPSD_PORT = int(os.environ.get("GPSD_PORT", "2947"))
GPS_READ_TIMEOUT = 5  # seconds

app = FastAPI(title="GPS Service")

# ── Shared state ─────────────────────────────────────────────────────────────

_position: dict[str, Any] = {
    "lat": 0.0,
    "lon": 0.0,
    "alt": 0.0,
    "speed": 0.0,
    "heading": 0.0,
    "fix": 0,
    "stale": True,
    "accuracy": None,
    "timestamp": datetime.now(timezone.utc).isoformat(),
}
_gps_connected: bool = False
_last_fix: str | None = None
_clients: set[WebSocket] = set()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a gpsd value to float, treating 'n/a' and None as default."""
    if value is None or value == "n/a":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or value == "n/a":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _blocking_read_gpsd() -> None:
    """Blocking loop: connect to gpsd, read data, update shared state.

    Uses gps3.GPSDSocket and DataStream directly (no threads) so that
    connection errors propagate immediately.  Intended to run inside
    asyncio.to_thread().
    """
    global _position, _gps_connected, _last_fix  # noqa: PLW0603

    gps_socket = agps3.GPSDSocket()
    data_stream = agps3.DataStream()

    # gps3's connect() swallows OSError, so we verify with our own probe.
    sock = socket.create_connection((GPSD_HOST, GPSD_PORT), timeout=GPS_READ_TIMEOUT)
    sock.close()

    gps_socket.connect(host=GPSD_HOST, port=GPSD_PORT)
    gps_socket.watch()

    # Verify the socket is usable (gps3 may have silently failed).
    if not gps_socket.streamSock:
        raise ConnectionError("gpsd socket not established")
    gps_socket.streamSock.settimeout(GPS_READ_TIMEOUT)

    _gps_connected = True
    logger.info("Connected to gpsd")

    import time
    for new_data in gps_socket:
        if not new_data:
            time.sleep(0.05)  # 50ms idle sleep prevents 100% CPU busy-wait
            continue
        if new_data:
            data_stream.unpack(new_data)

            mode = _safe_int(data_stream.mode)
            lat = _safe_float(data_stream.lat)
            lon = _safe_float(data_stream.lon)
            alt = _safe_float(data_stream.alt)
            speed = _safe_float(data_stream.speed)
            track = _safe_float(data_stream.track)

            # Horizontal accuracy (EPH) from epx/epy when available.
            epx_raw = getattr(data_stream, "epx", "n/a")
            epy_raw = getattr(data_stream, "epy", "n/a")
            if epx_raw not in (None, "n/a") and epy_raw not in (None, "n/a"):
                epx = _safe_float(epx_raw)
                epy = _safe_float(epy_raw)
                accuracy: float | None = round(sqrt(epx ** 2 + epy ** 2), 2)
            else:
                accuracy = None

            has_fix = mode >= 2 and lat != 0.0 and lon != 0.0
            now = datetime.now(timezone.utc).isoformat()

            _position = {
                "lat": lat,
                "lon": lon,
                "alt": alt,
                "speed": speed,
                "heading": track,
                "fix": mode if has_fix else 0,
                "stale": not has_fix,
                "accuracy": accuracy if has_fix else None,
                "timestamp": now,
            }

            if has_fix:
                _last_fix = now


# ── GPS reader background task ───────────────────────────────────────────────

async def _gps_reader() -> None:
    """Continuously attempt to read from gpsd, reconnecting on failure."""
    global _gps_connected, _position  # noqa: PLW0603

    while True:
        try:
            logger.info("Connecting to gpsd at %s:%s ...", GPSD_HOST, GPSD_PORT)
            await asyncio.to_thread(_blocking_read_gpsd)
        except Exception as exc:
            logger.warning("gpsd error: %s — retrying in 5 s", exc)
        finally:
            _gps_connected = False
            _position = {
                **_position,
                "stale": True,
                "fix": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        await asyncio.sleep(5)


# ── Broadcast loop ───────────────────────────────────────────────────────────

async def _broadcaster() -> None:
    """Send current position to every connected WebSocket client at 1 Hz."""
    while True:
        await asyncio.sleep(1)
        if not _clients:
            continue
        payload = json.dumps(_position)
        stale: list[WebSocket] = []
        for ws in _clients.copy():
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            _clients.discard(ws)


# ── Lifecycle events ─────────────────────────────────────────────────────────

@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_gps_reader())
    asyncio.create_task(_broadcaster())


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "gps_connected": _gps_connected,
        "last_fix": _last_fix,
    }


@app.get("/position")
async def position() -> dict[str, Any]:
    """Debug endpoint: returns current position dict including accuracy."""
    return _position


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    logger.info("Client connected (%d total)", len(_clients))
    try:
        # Keep the connection open; read frames so we detect disconnects.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
        logger.info("Client disconnected (%d remaining)", len(_clients))
