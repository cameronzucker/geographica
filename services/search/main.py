"""Unified search service combining Nominatim geocoding with local POI FTS5 database.

Also hosts the /admin/status endpoint for monitoring long-running tasks
(container health, import progress, download status).

Pipeline orchestration and credential management endpoints are also served here.
"""

import asyncio
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import aiosqlite
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "http://nominatim:8080")
POI_DB_PATH = os.environ.get("POI_DB_PATH", "/data/poi.sqlite")
CREDENTIALS_PATH = Path("/data/.credentials.json")
DATA_DIR = Path("/data")
TLS_CERT_PATH = Path("/tls/server.crt")

KNOWN_SERVICES = frozenset({
    "frontend", "gps", "nominatim", "search", "stt", "tileserver", "valhalla"
})

EARTH_RADIUS_M = 6_371_000

# Lock to prevent concurrent pipeline starts
_pipeline_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
async def require_config_source(
    x_config_source: str = Header(None),
    x_geographica: str = Header(None),
):
    """Verify request came through the config panel NGINX block.

    The config panel server block adds 'X-Config-Source: internal' header.
    Direct requests to port 8096 or through the public NGINX port won't
    have this header, so they're rejected.

    Also checks for the X-Geographica header as CSRF protection: its presence
    forces a CORS preflight which browsers block cross-origin.
    """
    if x_config_source != "internal":
        raise HTTPException(
            status_code=403,
            detail="Admin operations require access through the config panel (localhost:8097)",
        )
    if x_geographica is None:
        raise HTTPException(
            status_code=403,
            detail="Missing X-Geographica header (CSRF protection)",
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------
class CredentialBody(BaseModel):
    m2m_username: str = ""
    m2m_token: str = ""
    copernicus_username: str = ""
    copernicus_password: str = ""


class PipelineStartBody(BaseModel):
    type: str  # "imagery", "elevation", or "osm_poi"
    mode: Optional[str] = None  # "direct" or "m2m" (required for imagery/elevation)
    bbox: Optional[str] = None  # "west,south,east,north" (required for imagery/elevation)
    zoom: Optional[str] = None  # "min-max" (required for imagery/elevation)
    concurrency: int = 20
    update: bool = True


# ---------------------------------------------------------------------------
# Tile count estimation
# ---------------------------------------------------------------------------
def estimate_tile_count(bbox: tuple[float, float, float, float], zoom_min: int, zoom_max: int) -> int:
    """Estimate total tile count from bounding box and zoom range."""
    west, south, east, north = bbox
    total = 0
    for z in range(zoom_min, zoom_max + 1):
        n = 2 ** z
        x_min = int((west + 180) / 360 * n)
        x_max = int((east + 180) / 360 * n)
        y_min = int(
            (1 - math.log(math.tan(math.radians(north)) + 1 / math.cos(math.radians(north))) / math.pi) / 2 * n
        )
        y_max = int(
            (1 - math.log(math.tan(math.radians(south)) + 1 / math.cos(math.radians(south))) / math.pi) / 2 * n
        )
        total += (x_max - x_min + 1) * (y_max - y_min + 1)
    return total


def _parse_bbox(bbox_str: str) -> tuple[float, float, float, float]:
    """Parse bbox string into 4 floats. Raises ValueError on failure."""
    parts = bbox_str.split(",")
    if len(parts) != 4:
        raise ValueError("bbox must have exactly 4 comma-separated values")
    return tuple(float(p.strip()) for p in parts)  # type: ignore[return-value]


def _parse_zoom(zoom_str: str) -> tuple[int, int]:
    """Parse zoom string like '0-14' into (min, max). Raises ValueError on failure."""
    parts = zoom_str.split("-")
    if len(parts) != 2:
        raise ValueError("zoom must be in format 'min-max'")
    zoom_min, zoom_max = int(parts[0]), int(parts[1])
    if zoom_min < 0 or zoom_max > 19 or zoom_min > zoom_max:
        raise ValueError("zoom values must be 0-19 with min <= max")
    return zoom_min, zoom_max


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the distance in metres between two lat/lon points."""
    rlat1, rlon1, rlat2, rlon2 = (math.radians(v) for v in (lat1, lon1, lat2, lon2))
    dlat = rlat2 - rlat1
    dlon = rlon2 - rlon1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------
class State:
    poi_db: Optional[aiosqlite.Connection] = None
    poi_db_loaded: bool = False
    osm_pois_loaded: bool = False
    http_client: Optional[httpx.AsyncClient] = None


state = State()


async def _open_poi_db() -> None:
    """Open the POI SQLite database. Check each table independently."""
    try:
        if not Path(POI_DB_PATH).exists():
            return
        conn = await aiosqlite.connect(POI_DB_PATH, uri=False)
        conn.row_factory = aiosqlite.Row
        state.poi_db = conn

        # Check GNIS table (independent)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='poi_fts'"
        ) as cur:
            state.poi_db_loaded = (await cur.fetchone()) is not None

        # Check OSM POI table (independent)
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='osm_pois'"
        ) as cur:
            state.osm_pois_loaded = (await cur.fetchone()) is not None

        if state.osm_pois_loaded:
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_osm_pois_latlon ON osm_pois (lat, lon)"
            )
    except Exception:
        state.poi_db = None
        state.poi_db_loaded = False
        state.osm_pois_loaded = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    await _open_poi_db()
    # Ensure spatial index for bbox queries (corridor/proximity search)
    if state.poi_db and state.poi_db_loaded:
        await state.poi_db.execute(
            "CREATE INDEX IF NOT EXISTS idx_poi_latlon ON poi_features (lat, lon)"
        )
    yield
    # Shutdown
    if state.http_client:
        await state.http_client.aclose()
    if state.poi_db:
        await state.poi_db.close()


app = FastAPI(title="Geographica Search", lifespan=lifespan)

from spatial import router as spatial_router
app.include_router(spatial_router, prefix="")


# ---------------------------------------------------------------------------
# Nominatim query
# ---------------------------------------------------------------------------
async def _query_nominatim(
    q: str,
    limit: int,
    bbox: Optional[str],
) -> list[dict]:
    """Query the Nominatim instance and return normalised results."""
    params: dict = {
        "q": q,
        "format": "jsonv2",
        "limit": limit,
    }
    if bbox:
        # Nominatim expects viewbox=lon_min,lat_max,lon_max,lat_min (left,top,right,bottom)
        parts = bbox.split(",")
        if len(parts) == 4:
            lon_min, lat_min, lon_max, lat_max = parts
            params["viewbox"] = f"{lon_min},{lat_max},{lon_max},{lat_min}"
            params["bounded"] = 1

    try:
        resp = await state.http_client.get(f"{NOMINATIM_URL}/search", params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []

    results: list[dict] = []
    for item in data:
        try:
            results.append(
                {
                    "name": item.get("name") or item.get("display_name", ""),
                    "type": "address",
                    "class": item.get("category", item.get("class", "")),
                    "osm_category": item.get("category", ""),
                    "osm_type": item.get("type", ""),
                    "lat": float(item["lat"]),
                    "lon": float(item["lon"]),
                    "display_name": item.get("display_name", ""),
                }
            )
        except (KeyError, ValueError, TypeError):
            continue
    return results


# ---------------------------------------------------------------------------
# POI FTS5 query
# ---------------------------------------------------------------------------
async def _query_poi(
    q: str,
    limit: int,
    bbox: Optional[str],
) -> list[dict]:
    """Query the local FTS5 POI database and return normalised results."""
    if not state.poi_db_loaded or state.poi_db is None:
        return []

    # Build the FTS match expression. Escape double-quotes in user input.
    safe_q = q.replace('"', '""')
    fts_query = f'"{safe_q}"'

    sql = """
        SELECT f.name, f.class, f.state, f.county, f.lat, f.lon
        FROM poi_fts AS fts
        JOIN poi_features AS f ON f.rowid = fts.rowid
        WHERE poi_fts MATCH ?
    """
    params: list = [fts_query]

    if bbox:
        parts = bbox.split(",")
        if len(parts) == 4:
            try:
                lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
                sql += " AND f.lon BETWEEN ? AND ? AND f.lat BETWEEN ? AND ?"
                params.extend([lon_min, lon_max, lat_min, lat_max])
            except ValueError:
                pass

    sql += " LIMIT ?"
    params.append(limit)

    try:
        async with state.poi_db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    except Exception:
        return []

    results: list[dict] = []
    for row in rows:
        name = row[0] or ""
        cls = row[1] or ""
        s = row[2] or ""
        county = row[3] or ""
        lat = row[4]
        lon = row[5]
        display_parts = [p for p in (name, county, s) if p]
        results.append(
            {
                "name": name,
                "type": "poi",
                "class": cls,
                "lat": float(lat),
                "lon": float(lon),
                "display_name": ", ".join(display_parts),
            }
        )
    return results


# ---------------------------------------------------------------------------
# OSM POI FTS5 query
# ---------------------------------------------------------------------------
async def _query_osm_pois(
    q: str,
    limit: int,
    bbox: Optional[str],
) -> list[dict]:
    """Query the OSM POI FTS5 index and return normalised results."""
    if not state.osm_pois_loaded or state.poi_db is None:
        return []

    # Token-based matching (OR), not phrase matching.
    # "Shell fuel" becomes: "Shell" OR "fuel"
    # This matches across columns: "Shell" in name, "fuel" in osm_value
    tokens = q.split()
    safe_tokens = [t.replace('"', '""') for t in tokens if len(t) > 1]
    if not safe_tokens:
        return []
    fts_query = " OR ".join(f'"{t}"' for t in safe_tokens)

    sql = """
        SELECT o.name, o.osm_key, o.osm_value, o.operator, o.lat, o.lon
        FROM osm_fts AS fts
        JOIN osm_pois AS o ON o.rowid = fts.rowid
        WHERE osm_fts MATCH ?
    """
    params: list = [fts_query]

    if bbox:
        parts = bbox.split(",")
        if len(parts) == 4:
            try:
                lon_min, lat_min, lon_max, lat_max = (float(p) for p in parts)
                sql += " AND o.lon BETWEEN ? AND ? AND o.lat BETWEEN ? AND ?"
                params.extend([lon_min, lon_max, lat_min, lat_max])
            except ValueError:
                pass

    sql += " LIMIT ?"
    params.append(limit)

    try:
        async with state.poi_db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    except Exception:
        return []

    results: list[dict] = []
    for row in rows:
        name = row[0] or ""
        osm_key = row[1] or ""
        osm_value = row[2] or ""
        operator = row[3]
        lat = row[4]
        lon = row[5]
        results.append(
            {
                "name": name,
                "type": "osm_poi",
                "osm_key": osm_key,
                "osm_value": osm_value,
                "operator": operator,
                "lat": float(lat),
                "lon": float(lon),
                "display_name": f"{name} ({osm_value})" if osm_value else name,
            }
        )
    return results


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------
def _deduplicate(
    nominatim_results: list[dict],
    poi_results: list[dict],
    osm_poi_results: list[dict] | None = None,
) -> list[dict]:
    """Merge results, dropping lower-priority entries within 100m.

    Priority order: Nominatim > GNIS > OSM POI.
    Third argument defaults to None for backward compatibility.
    """
    merged = list(nominatim_results)

    # Add GNIS results, dedup against Nominatim
    for poi in poi_results:
        dominated = False
        for existing in merged:
            try:
                dist = haversine_m(poi["lat"], poi["lon"], existing["lat"], existing["lon"])
                if dist <= 100:
                    dominated = True
                    break
            except (KeyError, TypeError, ValueError):
                continue
        if not dominated:
            merged.append(poi)

    # Add OSM POI results, dedup against Nominatim + GNIS
    if osm_poi_results:
        for osm_poi in osm_poi_results:
            dominated = False
            for existing in merged:
                try:
                    dist = haversine_m(osm_poi["lat"], osm_poi["lon"],
                                       existing["lat"], existing["lon"])
                    if dist <= 100:
                        dominated = True
                        break
                except (KeyError, TypeError, ValueError):
                    continue
            if not dominated:
                merged.append(osm_poi)

    return merged


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query string"),
    limit: int = Query(10, ge=1, le=100, description="Maximum results"),
    bbox: Optional[str] = Query(
        None,
        description="Bounding box as lon_min,lat_min,lon_max,lat_max",
    ),
):
    nominatim_task = asyncio.create_task(_query_nominatim(q, limit, bbox))
    poi_task = asyncio.create_task(_query_poi(q, limit, bbox))
    osm_task = asyncio.create_task(_query_osm_pois(q, limit, bbox))

    nominatim_results, poi_results, osm_results = await asyncio.gather(
        nominatim_task, poi_task, osm_task, return_exceptions=True
    )

    # If any leg raised, treat as empty.
    if isinstance(nominatim_results, BaseException):
        nominatim_results = []
    if isinstance(poi_results, BaseException):
        poi_results = []
    if isinstance(osm_results, BaseException):
        osm_results = []

    merged = _deduplicate(nominatim_results, poi_results, osm_results)
    return {"results": merged[:limit]}


@app.get("/health")
async def health():
    nominatim_available = False
    try:
        resp = await state.http_client.get(f"{NOMINATIM_URL}/status", timeout=2.0)
        nominatim_available = resp.status_code == 200
    except Exception:
        pass

    return {
        "status": "ok",
        "nominatim_available": nominatim_available,
        "poi_db_loaded": state.poi_db_loaded,
        "osm_pois_loaded": state.osm_pois_loaded,
    }


# ---------------------------------------------------------------------------
# Admin task monitor
# ---------------------------------------------------------------------------

def _get_docker_client():
    """Lazy-load Docker client. Returns None if socket unavailable."""
    try:
        import docker
        return docker.DockerClient(base_url="unix:///var/run/docker.sock", timeout=5)
    except Exception:
        return None


def _parse_progress_from_logs(logs: str, container_name: str) -> dict:
    """Extract progress indicators from recent container logs."""
    lines = logs.strip().split("\n")
    if not lines:
        return {}

    progress = {}

    # Nominatim: "rank 30 ETA (seconds): 1234.56" or "FINISHED rank 30"
    for line in reversed(lines):
        m = re.search(r"rank\s+(\d+)\s+ETA\s*\(seconds\):\s*([\d.]+)", line)
        if m:
            progress["phase"] = f"Indexing rank {m.group(1)}"
            eta_sec = float(m.group(2))
            if eta_sec > 3600:
                progress["eta"] = f"{eta_sec/3600:.1f} hours"
            elif eta_sec > 60:
                progress["eta"] = f"{eta_sec/60:.0f} min"
            else:
                progress["eta"] = f"{eta_sec:.0f} sec"
            break

        if "FINISHED" in line and "rank" in line:
            progress["phase"] = "Indexing complete"
            break

        if "Post-process tables" in line:
            progress["phase"] = "Post-processing"
            break

        if "Application startup complete" in line:
            progress["phase"] = "Ready"
            break

        # Valhalla progress
        if "Parsing nodes" in line or "Parsing ways" in line:
            progress["phase"] = line.strip().split("]")[-1].strip()[:60]
            break

        if "Finished building" in line or "available_actions" in line:
            progress["phase"] = "Ready"
            break

    return progress


async def _fetch_stt_status() -> dict:
    """Query STT service health with 2s timeout."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://stt:8000/health")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": data.get("status", "ok"),
                    "backend": data.get("backend"),
                    "model": data.get("model"),
                    "npu_available": data.get("npu_available"),
                }
    except Exception:
        pass
    return {"status": "unreachable", "backend": None, "model": None, "npu_available": None}


async def _fetch_gps_status() -> dict:
    """Query GPS service status with 2s timeout. Never returns coordinates."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get("http://gps:8000/status")
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "status": data.get("status", "ok"),
                    "fix": data.get("fix"),
                    "accuracy_m": data.get("accuracy_m"),
                }
    except Exception:
        pass
    return {"status": "unreachable", "fix": None, "accuracy_m": None}


def _detect_tls_status() -> dict:
    """Detect TLS mode from cert file at /tls/server.crt."""
    result = {"mode": "http", "hostname": None, "cert_expires": None, "cert_valid": None}

    if not TLS_CERT_PATH.exists():
        return result

    # Parse certificate expiry
    try:
        enddate_result = subprocess.run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(TLS_CERT_PATH)],
            capture_output=True, text=True, timeout=5,
        )
        if enddate_result.returncode == 0:
            raw = enddate_result.stdout.strip().split("=", 1)[-1]
            from datetime import datetime, timezone
            expiry = datetime.strptime(raw, "%b %d %H:%M:%S %Y GMT").replace(tzinfo=timezone.utc)
            result["cert_expires"] = expiry.strftime("%Y-%m-%d")
            result["cert_valid"] = expiry > datetime.now(timezone.utc)
    except Exception:
        pass

    # Parse certificate subject for hostname and detect Tailscale
    try:
        subject_result = subprocess.run(
            ["openssl", "x509", "-subject", "-noout", "-in", str(TLS_CERT_PATH)],
            capture_output=True, text=True, timeout=5,
        )
        if subject_result.returncode == 0:
            subject = subject_result.stdout.strip()
            cn_match = re.search(r"CN\s*=\s*(.+?)(?:,|$)", subject)
            if cn_match:
                cn = cn_match.group(1).strip()
                if ".ts.net" in cn:
                    result["mode"] = "tailscale"
                    result["hostname"] = cn
                else:
                    result["mode"] = "https"
                    result["hostname"] = cn
    except Exception:
        if result["cert_expires"]:
            result["mode"] = "https"

    return result


def _get_search_stats() -> dict:
    """Get POI counts from the SQLite database."""
    import sqlite3
    stats = {"gnis_count": 0, "osm_pois_count": 0, "osm_pois_loaded": False}
    try:
        conn = sqlite3.connect(POI_DB_PATH, timeout=5)
        try:
            stats["gnis_count"] = conn.execute("SELECT COUNT(*) FROM poi_features").fetchone()[0]
        except Exception:
            pass
        try:
            stats["osm_pois_count"] = conn.execute("SELECT COUNT(*) FROM osm_pois").fetchone()[0]
            stats["osm_pois_loaded"] = stats["osm_pois_count"] > 0
        except Exception:
            pass
        conn.close()
    except Exception:
        pass
    return stats


def _get_disk_info() -> tuple:
    """Return (free_gb, total_gb, used_pct) for the /data partition."""
    try:
        path = str(DATA_DIR) if DATA_DIR.exists() else "/"
    except Exception:
        path = "/"
    usage = shutil.disk_usage(path)
    free_gb = round(usage.free / (1024 ** 3), 1)
    total_gb = round(usage.total / (1024 ** 3), 1)
    used_pct = round(100 - (usage.free / usage.total * 100))
    return free_gb, total_gb, used_pct


def _list_docker_services() -> list[dict]:
    """List Docker services (runs synchronously — call via to_thread)."""
    services = []
    client = _get_docker_client()
    if not client:
        return services
    try:
        containers = client.containers.list(all=True, filters={"name": "geographica-"})
        for c in sorted(containers, key=lambda x: x.name):
            svc_name = c.name.replace("geographica-", "")
            if svc_name not in KNOWN_SERVICES:
                continue
            svc = {
                "name": svc_name,
                "status": c.status,
                "health": "unknown",
                "uptime": "",
                "progress": {},
            }

            # Health from inspect
            try:
                inspection = c.attrs
                health_data = inspection.get("State", {}).get("Health", {})
                svc["health"] = health_data.get("Status", "none")
                started = inspection.get("State", {}).get("StartedAt", "")
                if started:
                    svc["uptime"] = started
            except Exception:
                pass

            # Parse logs for progress on key services
            if c.name in ("geographica-nominatim", "geographica-valhalla") and c.status == "running":
                try:
                    logs = c.logs(tail=30, timestamps=False).decode("utf-8", errors="replace")
                    svc["progress"] = _parse_progress_from_logs(logs, c.name)
                except Exception:
                    pass

            services.append(svc)
    except Exception:
        pass
    finally:
        client.close()
    return services


@app.get("/admin/status")
async def admin_status():
    """Return status of all Geographica services and long-running tasks.

    All blocking calls (Docker, TLS, search stats, disk) run in thread pool
    to avoid stalling the async event loop during the 10s poll cycle.
    """
    # --- All sub-queries run concurrently ---
    (services, stt_data, gps_data, tls_data, search_stats,
     disk_info) = await asyncio.gather(
        asyncio.to_thread(_list_docker_services),
        _fetch_stt_status(),
        _fetch_gps_status(),
        asyncio.to_thread(_detect_tls_status),
        asyncio.to_thread(_get_search_stats),
        asyncio.to_thread(_get_disk_info),
        return_exceptions=True,
    )

    # Fallbacks for any failed sub-queries
    if isinstance(services, Exception):
        services = []
    if isinstance(stt_data, Exception):
        stt_data = {"status": "unreachable", "backend": None, "model": None, "npu_available": None}
    if isinstance(gps_data, Exception):
        gps_data = {"status": "unreachable", "fix": None, "accuracy_m": None}
    if isinstance(tls_data, Exception):
        tls_data = {"mode": "http", "hostname": None, "cert_expires": None, "cert_valid": None}
    if isinstance(search_stats, Exception):
        search_stats = {"gnis_count": 0, "osm_pois_count": 0, "osm_pois_loaded": False}
    if isinstance(disk_info, Exception):
        disk_info = (0.0, 0.0, 0)
    disk_free_gb, disk_total_gb, disk_used_pct = disk_info

    # --- Data pipeline files (downloads in progress) ---
    data_tasks = []
    import pathlib
    data_dir = pathlib.Path("/data")

    def _read_mbtiles_status(path, name):
        """Read tile count from an MBTiles file.

        With WAL mode enabled on the writers, readers never block.
        """
        import sqlite3
        try:
            conn = sqlite3.connect(str(path), timeout=5)
            tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            has_checkpoint = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='_checkpoint'"
            ).fetchone()[0]
            conn.close()
            return {
                "name": name,
                "tiles": tile_count,
                "status": "downloading" if has_checkpoint else "complete",
            }
        except Exception:
            return {"name": name, "status": "error"}

    # Elevation MBTiles — enrich with state file if available
    elev_path = data_dir / "elevation.mbtiles"
    if elev_path.exists():
        task = _read_mbtiles_status(elev_path, "Elevation tiles")
        elev_state = data_dir / ".elevation-state.json"
        if elev_state.exists():
            try:
                es = json.loads(elev_state.read_text())
                task["tiles_total"] = es.get("tiles_total")
                task["rate"] = es.get("rate_per_sec")
                if es.get("status") in ("completed", "cancelled"):
                    task["status"] = es["status"]
            except Exception:
                pass
        data_tasks.append(task)

    # Imagery MBTiles — enrich with state file if available
    imagery_path = data_dir / "imagery.mbtiles"
    if imagery_path.exists():
        task = _read_mbtiles_status(imagery_path, "Imagery tiles")
        img_state = data_dir / ".pipeline-state.json"
        if img_state.exists():
            try:
                ps = json.loads(img_state.read_text())
                if ps.get("type") == "imagery":
                    # Use estimated_tiles from the job config (based on bbox+zoom)
                    # not tiles_total from progress (which may be from a different run)
                    est = ps.get("estimated_tiles")
                    prog_total = ps.get("tiles_total")
                    # Pick the larger of estimated vs progress total to avoid >100%
                    if est and prog_total:
                        task["tiles_total"] = max(est, prog_total)
                    else:
                        task["tiles_total"] = est or prog_total
                    # Ensure tiles_total is never less than actual tile count
                    if task.get("tiles_total") and task["tiles"] > task["tiles_total"]:
                        task["tiles_total"] = task["tiles"]
                    task["rate"] = ps.get("rate_per_sec")
                    if ps.get("status") in ("completed", "cancelled"):
                        task["status"] = ps["status"]
            except Exception:
                pass
        data_tasks.append(task)

    # POI database
    poi_path = data_dir / "poi.sqlite"
    if poi_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(poi_path))
            count = conn.execute("SELECT COUNT(*) FROM poi_features").fetchone()[0]
            conn.close()
            data_tasks.append({
                "name": "POI index",
                "features": count,
                "status": "complete",
            })
        except Exception:
            pass

    return {
        "services": services,
        "data_tasks": data_tasks,
        "stt": stt_data,
        "gps": gps_data,
        "tls": tls_data,
        "search_stats": search_stats,
        "disk_free_gb": disk_free_gb,
        "disk_total_gb": disk_total_gb,
        "disk_used_pct": disk_used_pct,
    }


# ---------------------------------------------------------------------------
# Credential management
# ---------------------------------------------------------------------------
_credential_lock = asyncio.Lock()


async def _remove_credential_keys(keys_to_remove: list) -> dict:
    """Remove specified credential keys, deleting the file if none remain."""
    async with _credential_lock:
        existing = {}
        try:
            existing = json.loads(CREDENTIALS_PATH.read_text())
        except FileNotFoundError:
            pass

        for key in keys_to_remove:
            existing.pop(key, None)

        known_keys = {"m2m_username", "m2m_token", "copernicus_username", "copernicus_password"}
        has_remaining = any(existing.get(k) for k in known_keys)

        if has_remaining:
            cred_data = json.dumps(existing)
            fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
            try:
                os.write(fd, cred_data.encode())
            finally:
                os.close(fd)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, str(CREDENTIALS_PATH))
        else:
            CREDENTIALS_PATH.unlink(missing_ok=True)

    return {"status": "deleted"}


@app.post("/admin/credentials", dependencies=[Depends(require_config_source)])
async def save_credentials(body: CredentialBody):
    """Store API credentials securely. Supports M2M and/or Copernicus credentials."""
    has_m2m = body.m2m_username.strip() and body.m2m_token.strip()
    has_copernicus = body.copernicus_username.strip() and body.copernicus_password.strip()

    if not has_m2m and not has_copernicus:
        raise HTTPException(status_code=422, detail="Provide m2m_username+m2m_token and/or copernicus_username+copernicus_password")

    async with _credential_lock:
        # Merge with existing credentials (don't overwrite one type when saving the other)
        existing = {}
        if CREDENTIALS_PATH.exists():
            try:
                existing = json.loads(CREDENTIALS_PATH.read_text())
            except (json.JSONDecodeError, OSError):
                pass

        if has_m2m:
            existing["m2m_username"] = body.m2m_username
            existing["m2m_token"] = body.m2m_token
        if has_copernicus:
            existing["copernicus_username"] = body.copernicus_username
            existing["copernicus_password"] = body.copernicus_password

        cred_data = json.dumps(existing)

        # Atomic write: write to temp file, then os.replace
        try:
            fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
            try:
                os.write(fd, cred_data.encode())
            finally:
                os.close(fd)
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            os.replace(tmp_path, str(CREDENTIALS_PATH))
        except Exception as e:
            # Clean up temp file if replace failed
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            log.error("Failed to save credentials: %s", e)
            raise HTTPException(status_code=500, detail="Failed to save credentials. Check server logs.")

    return {"status": "saved"}


@app.get("/admin/credentials/status")
async def credentials_status():
    """Check if credentials are configured (no auth required)."""
    m2m = False
    copernicus = False
    if CREDENTIALS_PATH.exists():
        try:
            creds = json.loads(CREDENTIALS_PATH.read_text())
            m2m = bool(creds.get("m2m_username") and creds.get("m2m_token"))
            copernicus = bool(creds.get("copernicus_username") and creds.get("copernicus_password"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"m2m_configured": m2m, "copernicus_configured": copernicus}


@app.delete("/admin/credentials", dependencies=[Depends(require_config_source)])
async def delete_credentials():
    """Remove stored credentials."""
    try:
        CREDENTIALS_PATH.unlink(missing_ok=True)
    except Exception as e:
        log.error("Failed to delete credentials: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete credentials. Check server logs.")
    return {"status": "deleted"}


@app.delete("/admin/credentials/m2m", dependencies=[Depends(require_config_source)])
async def delete_m2m_credentials():
    """Remove only M2M credentials, preserving Copernicus."""
    try:
        return await _remove_credential_keys(["m2m_username", "m2m_token"])
    except Exception as e:
        log.error("Failed to delete M2M credentials: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete credentials. Check server logs.")


@app.delete("/admin/credentials/copernicus", dependencies=[Depends(require_config_source)])
async def delete_copernicus_credentials():
    """Remove only Copernicus credentials, preserving M2M."""
    try:
        return await _remove_credential_keys(["copernicus_username", "copernicus_password"])
    except Exception as e:
        log.error("Failed to delete Copernicus credentials: %s", e)
        raise HTTPException(status_code=500, detail="Failed to delete credentials. Check server logs.")


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------
def _state_file_for_type(pipeline_type: str) -> Path:
    """Return the state file path for a given pipeline type."""
    if pipeline_type == "elevation":
        return DATA_DIR / ".elevation-state.json"
    if pipeline_type == "osm_poi":
        return DATA_DIR / ".osm-poi-state.json"
    if pipeline_type == "sentinel":
        return DATA_DIR / ".sentinel-state.json"
    if pipeline_type == "naip":
        return DATA_DIR / ".naip-state.json"
    return DATA_DIR / ".pipeline-state.json"


def _mbtiles_path_for_type(pipeline_type: str) -> Path:
    """Return the mbtiles output path for a given pipeline type."""
    if pipeline_type == "elevation":
        return DATA_DIR / "elevation.mbtiles"
    if pipeline_type == "sentinel":
        return DATA_DIR / "imagery_sentinel.mbtiles"
    if pipeline_type == "naip":
        return DATA_DIR / "imagery_naip.mbtiles"
    return DATA_DIR / "imagery.mbtiles"


def _script_for_type(pipeline_type: str) -> str:
    """Return the script path for a given pipeline type."""
    if pipeline_type == "elevation":
        return "/scripts/download_elevation.py"
    if pipeline_type == "sentinel":
        return "/scripts/acquire_sentinel.py"
    if pipeline_type == "naip":
        return "/scripts/acquire_naip.py"
    return "/scripts/acquire_imagery.py"


def _is_pipeline_container_running(client) -> bool:
    """Check if any pipeline container is currently running.

    Matches both admin-started containers (geographica-pipeline) and
    CLI-started ones (geographica-pipeline-run-*).
    """
    try:
        containers = client.containers.list(
            all=False, filters={"name": "geographica-pipeline"}
        )
        return any(c.status == "running" for c in containers)
    except Exception:
        return False


def _get_disk_free_gb() -> float:
    """Return free disk space in GB for the /data partition."""
    usage = shutil.disk_usage(str(DATA_DIR))
    return usage.free / (1024 ** 3)


@app.post("/admin/pipeline/start", dependencies=[Depends(require_config_source)])
async def pipeline_start(body: PipelineStartBody):
    """Start an imagery, elevation, or OSM POI pipeline."""
    # Validate type
    if body.type not in ("imagery", "elevation", "osm_poi", "sentinel", "naip"):
        raise HTTPException(status_code=422, detail="type must be 'imagery', 'elevation', 'osm_poi', 'sentinel', or 'naip'")

    # For imagery/elevation, validate required fields
    bbox = None
    zoom_min = zoom_max = tile_count = 0
    estimated_size_gb = 0.0
    is_m2m = body.type == "imagery" and body.mode == "m2m"
    is_sentinel = body.type == "sentinel"
    is_naip = body.type == "naip"

    # Sentinel validation: requires bbox and Copernicus credentials
    if is_sentinel:
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for sentinel")
        if not CREDENTIALS_PATH.exists():
            raise HTTPException(status_code=422, detail="Copernicus credentials not configured. POST to /admin/credentials first.")
        try:
            creds = json.loads(CREDENTIALS_PATH.read_text())
            if "copernicus_username" not in creds or "copernicus_password" not in creds:
                raise HTTPException(status_code=422, detail="credentials.json missing copernicus_username or copernicus_password")
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=500, detail=f"Failed to read credentials: {e}")

    # NAIP validation: requires bbox only
    if is_naip:
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for naip")

    if body.type in ("imagery", "elevation"):
        if not body.mode or body.mode not in ("direct", "m2m"):
            raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for imagery/elevation")
        if not is_m2m and not body.zoom:
            raise HTTPException(status_code=422, detail="zoom is required for imagery/elevation")

        # Parse and validate bbox
        try:
            bbox = _parse_bbox(body.bbox)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"Invalid bbox: {e}")

        # Parse and validate zoom (not required for M2M)
        if body.zoom:
            try:
                zoom_min, zoom_max = _parse_zoom(body.zoom)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"Invalid zoom: {e}")

        # Estimate tile count and check disk space (skip for M2M — auto-detected)
        if not is_m2m:
            tile_count = estimate_tile_count(bbox, zoom_min, zoom_max)
            estimated_size_gb = tile_count * 20 * 1024 / (1024 ** 3)
            disk_free_gb = _get_disk_free_gb()
            if disk_free_gb - estimated_size_gb < 10.0:
                raise HTTPException(
                    status_code=507,
                    detail=f"Insufficient disk space. Free: {disk_free_gb:.1f} GB, estimated need: {estimated_size_gb:.1f} GB, minimum 10 GB buffer required",
                )

    # For M2M mode, verify credentials exist
    if body.mode == "m2m":
        if not CREDENTIALS_PATH.exists():
            raise HTTPException(status_code=422, detail="M2M credentials not configured. POST to /admin/credentials first.")
        try:
            creds = json.loads(CREDENTIALS_PATH.read_text())
            if not creds.get("m2m_username") or not creds.get("m2m_token"):
                raise HTTPException(status_code=422, detail="M2M credentials not configured. POST to /admin/credentials first.")
        except json.JSONDecodeError:
            raise HTTPException(status_code=422, detail="Credentials file is corrupted.")

    async with _pipeline_lock:
        client = _get_docker_client()
        if not client:
            raise HTTPException(status_code=503, detail="Docker socket not available")

        try:
            # Check if a pipeline is already running
            if _is_pipeline_container_running(client):
                raise HTTPException(status_code=409, detail="A pipeline job is already running")

            # Also check state file
            state_file = _state_file_for_type(body.type)
            if state_file.exists():
                try:
                    state_data = json.loads(state_file.read_text())
                    if state_data.get("status") == "running" and _is_pipeline_container_running(client):
                        raise HTTPException(status_code=409, detail="A pipeline job is already running")
                except json.JSONDecodeError:
                    pass

            # Check pipeline image exists
            try:
                client.images.get("geographica-pipeline")
            except Exception:
                raise HTTPException(
                    status_code=422,
                    detail="Pipeline image not built. Run 'docker compose build pipeline' first.",
                )

            # Build command based on pipeline type
            if body.type == "osm_poi":
                import glob as _glob
                pbf_files = _glob.glob(str(DATA_DIR / "valhalla" / "*.osm.pbf"))
                if not pbf_files:
                    raise HTTPException(status_code=422, detail="No OSM PBF file found in /data/valhalla/")
                pbf_filename = Path(pbf_files[0]).name
                command = [
                    "python3", "/scripts/build_osm_pois.py",
                    "--pbf", f"/data/valhalla/{pbf_filename}",
                    "--output", "/data/poi.sqlite",
                ]
                if body.bbox:
                    command.extend(["--bbox", body.bbox])
            else:
                # Handle existing mbtiles if not updating
                mbtiles_path = _mbtiles_path_for_type(body.type)
                if not body.update and mbtiles_path.exists():
                    prev_path = mbtiles_path.with_suffix(".mbtiles.prev")
                    try:
                        os.replace(str(mbtiles_path), str(prev_path))
                    except Exception as e:
                        raise HTTPException(status_code=500, detail=f"Failed to rename existing file: {e}")

                if is_m2m:
                    # M2M command: no --zoom, add --staging
                    command = [
                        "python3", "/scripts/acquire_imagery.py",
                        "--mode", "m2m",
                        f"--bbox={body.bbox}",
                        "--output", f"/data/{mbtiles_path.name}",
                        "--staging", "/data/m2m_staging",
                        "--concurrency", str(body.concurrency),
                    ]
                elif is_sentinel:
                    command = [
                        "python3", "/scripts/acquire_sentinel.py",
                        f"--bbox={body.bbox}",
                        "--output", f"/data/{mbtiles_path.name}",
                        "--staging", "/data/sentinel_staging",
                    ]
                elif is_naip:
                    command = [
                        "python3", "/scripts/acquire_naip.py",
                        f"--bbox={body.bbox}",
                        "--output", f"/data/{mbtiles_path.name}",
                        "--staging", "/data/naip_staging",
                        "--counties-db", "/data/counties.sqlite",
                    ]
                else:
                    # Build command -- imagery and elevation scripts have different args
                    script = _script_for_type(body.type)
                    command = [
                        "python3", script,
                        f"--bbox={body.bbox}",
                        f"--zoom={body.zoom}",
                        "--concurrency", str(body.concurrency),
                        "--output", f"/data/{mbtiles_path.name}",
                    ]
                    if body.type == "imagery":
                        command[2:2] = ["--mode", body.mode]

            # Build environment
            env = {
                "GDAL_CACHEMAX": "1024",
                "PYTHONUNBUFFERED": "1",
            }
            if body.mode == "m2m":
                try:
                    creds = json.loads(CREDENTIALS_PATH.read_text())
                    env["USGS_M2M_USERNAME"] = creds["m2m_username"]
                    env["USGS_M2M_TOKEN"] = creds["m2m_token"]
                except (json.JSONDecodeError, KeyError) as e:
                    raise HTTPException(status_code=500, detail=f"Failed to read credentials: {e}")
            if is_sentinel:
                try:
                    creds = json.loads(CREDENTIALS_PATH.read_text())
                    env["COPERNICUS_USERNAME"] = creds["copernicus_username"]
                    env["COPERNICUS_PASSWORD"] = creds["copernicus_password"]
                except (json.JSONDecodeError, KeyError) as e:
                    raise HTTPException(status_code=500, detail=f"Failed to read credentials: {e}")

            # Find the compose network
            try:
                networks = client.networks.list(names=["geographica_default"])
                network = networks[0].name if networks else "bridge"
            except Exception:
                network = "bridge"

            # Resolve volume paths - match the compose definition for pipeline service
            # The compose file maps ./scripts:/scripts:ro and ./data:/data
            # From inside the search container, /data is already the host's ./data mount
            # Resolve host paths for Docker SDK volume mounts.
            # Use DATA_HOST_PATH env var if set (preferred), otherwise
            # introspect from the search container's own mounts.
            host_data_path = os.environ.get("DATA_HOST_PATH", "")
            host_scripts_path = os.environ.get("SCRIPTS_HOST_PATH", "")

            if not host_data_path:
                try:
                    search_container = client.containers.get("geographica-search")
                    mounts = search_container.attrs.get("Mounts", [])
                    for mount in mounts:
                        if mount.get("Destination") == "/data":
                            host_data_path = mount.get("Source", "")
                            host_base = os.path.dirname(host_data_path)
                            if not host_scripts_path:
                                host_scripts_path = os.path.join(host_base, "scripts")
                            break
                except Exception:
                    pass

            if not host_data_path:
                raise HTTPException(
                    status_code=500,
                    detail="Cannot determine host data path. Set DATA_HOST_PATH env var."
                )

            volumes = {
                host_data_path: {"bind": "/data", "mode": "rw"},
            }
            if host_scripts_path:
                volumes[host_scripts_path] = {"bind": "/scripts", "mode": "ro"}

            # Remove any stale pipeline container before starting
            try:
                old = client.containers.get("geographica-pipeline")
                old.remove(force=True)
            except Exception:
                pass

            # Start the pipeline container
            container = client.containers.run(
                "geographica-pipeline",
                command=command,
                name="geographica-pipeline",
                detach=True,
                remove=False,  # Keep container for log capture on failure
                volumes=volumes,
                environment=env,
                network=network,
                mem_limit="2g",
            )

            # Write state file
            from datetime import datetime, timezone as tz
            state_data = {
                "status": "running",
                "type": body.type,
                "mode": body.mode,
                "bbox": body.bbox,
                "zoom": body.zoom if not is_m2m else "n/a",
                "phase": "login" if is_m2m else None,
                "concurrency": body.concurrency,
                "update": body.update,
                "estimated_tiles": tile_count if body.type != "osm_poi" and not is_m2m else None,
                "container_id": container.id,
                "started_at": datetime.now(tz.utc).isoformat(),
            }
            state_file.write_text(json.dumps(state_data, indent=2))

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start pipeline: {e}")
        finally:
            client.close()

    return {"status": "started"}


@app.get("/admin/pipeline/status")
async def pipeline_status(type: str = Query("imagery", description="Pipeline type: imagery, elevation, or osm_poi")):
    """Get current pipeline job status (no auth required)."""
    if type not in ("imagery", "elevation", "osm_poi"):
        raise HTTPException(status_code=422, detail="type must be 'imagery', 'elevation', or 'osm_poi'")

    state_file = _state_file_for_type(type)
    state_data = {}
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            state_data = {"status": "unknown", "error": "Could not read state file"}

    # Check container status — keep client alive through reconciliation for log capture
    client = _get_docker_client()
    container_running = False
    try:
        if client:
            try:
                container_running = _is_pipeline_container_running(client)
            except Exception:
                pass

        # Reconcile: if state says running but container is dead, mark interrupted
        # and capture last logs for crash diagnosis
        if state_data.get("status") in ("running", "cancelling") and not container_running:
            # Add completion timestamps
            from datetime import datetime, timezone as tz
            state_data["completed_at"] = datetime.now(tz.utc).isoformat()
            if state_data.get("started_at"):
                started = datetime.fromisoformat(state_data["started_at"])
                state_data["duration_seconds"] = int((datetime.now(tz.utc) - started).total_seconds())

            # Capture last logs from dead container (client still open)
            if client:
                try:
                    container = client.containers.get("geographica-pipeline")
                    logs = container.logs(tail=50, timestamps=False).decode("utf-8", errors="replace")
                    state_data["last_logs"] = logs[-2000:]  # cap at 2KB
                except Exception:
                    pass

            # Determine final status: check logs for success before marking interrupted
            if state_data.get("status") == "cancelling":
                new_status = "cancelled"
            elif "MBTiles written to" in (state_data.get("last_logs") or ""):
                new_status = "completed"
            else:
                new_status = "interrupted"
            state_data["status"] = new_status

            try:
                tmp = state_file.with_suffix(".json.tmp")
                tmp.write_text(json.dumps(state_data, indent=2))
                os.replace(str(tmp), str(state_file))
            except OSError:
                pass
    finally:
        if client:
            client.close()

    # Add live fields
    state_data["container_running"] = container_running

    # Calculate estimated tiles if bbox/zoom available (skip for osm_poi/M2M)
    if (state_data.get("bbox") and state_data.get("zoom")
            and state_data.get("zoom") != "n/a"):
        try:
            bbox = _parse_bbox(state_data["bbox"])
            zoom_min, zoom_max = _parse_zoom(state_data["zoom"])
            state_data["estimated_tiles"] = estimate_tile_count(bbox, zoom_min, zoom_max)
        except (ValueError, TypeError):
            pass

    state_data["disk_free_gb"] = round(_get_disk_free_gb(), 2)

    return state_data


@app.post("/admin/pipeline/cancel", dependencies=[Depends(require_config_source)])
async def pipeline_cancel():
    """Cancel a running pipeline."""
    async with _pipeline_lock:
        # Write "cancelling" to all possible state files immediately
        for state_file in [
            _state_file_for_type("imagery"),
            _state_file_for_type("elevation"),
            _state_file_for_type("osm_poi"),
            _state_file_for_type("sentinel"),
            _state_file_for_type("naip"),
        ]:
            if state_file.exists():
                try:
                    existing = json.loads(state_file.read_text())
                    if existing.get("status") == "running":
                        existing["status"] = "cancelling"
                        tmp = state_file.with_suffix(".json.tmp")
                        tmp.write_text(json.dumps(existing, indent=2))
                        os.replace(str(tmp), str(state_file))
                except Exception:
                    pass

        client = _get_docker_client()
        if not client:
            raise HTTPException(status_code=503, detail="Docker socket not available")

        try:
            container = client.containers.get("geographica-pipeline")
            container.stop(timeout=30)
        except Exception:
            pass
        finally:
            client.close()

    return {"status": "cancelling"}


@app.get("/admin/pipeline/naip/counties", dependencies=[Depends(require_config_source)])
async def naip_county_lookup(bbox: str = Query(..., description="west,south,east,north")):
    """Return counties intersecting the given bbox for NAIP pipeline planning."""
    # Parse bbox
    try:
        parts = [float(x.strip()) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("bbox must have exactly 4 values")
        west, south, east, north = parts
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid bbox: {e}")

    # Import counties helper from scripts
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
    from build_county_index import counties_for_bbox, estimate_download_gb

    counties_db = DATA_DIR / "counties.sqlite"
    if not counties_db.exists():
        raise HTTPException(status_code=422, detail="counties.sqlite not found in data directory. Run build_county_index.py first.")

    try:
        rows = counties_for_bbox(str(counties_db), west, south, east, north)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"County lookup failed: {e}")

    if len(rows) > 1000:
        raise HTTPException(status_code=422, detail=f"Too many counties ({len(rows)}); refine your bbox to cover at most 1000 counties")

    total_area = sum(area for _, _, _, area in rows)
    states = sorted({state for _, _, state, _ in rows})
    estimated_gb = estimate_download_gb(total_area)

    counties = [
        {"fips": fips, "name": name, "state": state, "area_sq_km": area}
        for fips, name, state, area in rows
    ]

    return {
        "counties": counties,
        "total_counties": len(counties),
        "states": states,
        "estimated_gb": round(estimated_gb, 2),
    }
