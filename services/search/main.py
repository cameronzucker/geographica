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
import sqlite3
import stat
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import aiosqlite
import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import keyring_client

try:
    from scripts.common.state_bboxes import SLUG_BY_USPS, states_intersecting
    _STATE_BBOXES_AVAILABLE = True
except ImportError:  # search container may not have scripts/ on PYTHONPATH
    _STATE_BBOXES_AVAILABLE = False
    SLUG_BY_USPS: dict = {}  # type: ignore[assignment]

    def states_intersecting(bbox_str: str) -> list[str]:  # type: ignore[misc]
        return []

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "http://nominatim:8080")
POI_DB_PATH = os.environ.get("POI_DB_PATH", "/data/poi.sqlite")
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
    counties: Optional[str] = None  # comma-separated FIPS codes (for NAIP — overrides bbox county lookup)
    state: Optional[str] = None   # for NOAA mode
    year: Optional[int] = None    # for NOAA mode


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
    from geocode import init_geocode
    init_geocode(state.http_client, NOMINATIM_URL)
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


# ---------------------------------------------------------------------------
# Imagery catalog
# ---------------------------------------------------------------------------

def _tile_bounds_tms(z: int, min_x: int, max_x: int, min_y: int, max_y: int) -> list[float]:
    """Convert TMS tile coordinate range to [lon_min, lat_min, lon_max, lat_max].

    MBTiles uses TMS y-axis (y=0 at south pole). The slippy-map latitude formula
    assumes XYZ convention (y=0 at north pole), so we flip y before computing.
    """
    n = 2 ** z
    lon_min = min_x / n * 360 - 180
    lon_max = (max_x + 1) / n * 360 - 180
    # Flip TMS y to XYZ y before applying latitude formula
    xyz_min_y = n - 1 - max_y   # TMS max_y → XYZ min_y (northernmost)
    xyz_max_y = n - 1 - min_y   # TMS min_y → XYZ max_y (southernmost)
    lat_max = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * xyz_min_y / n))))
    lat_min = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (xyz_max_y + 1) / n))))
    return [round(lon_min, 6), round(lat_min, 6),
            round(lon_max, 6), round(lat_max, 6)]


def _cluster_tile_bounds(conn, z: int, gap_threshold: int = 10) -> list[list[float]]:
    """Find contiguous clusters of tiles at a given zoom and return their bounds.

    Groups tiles by row ranges. If there's a gap of more than gap_threshold
    rows between consecutive groups of tiles, they're split into separate
    clusters. Each cluster gets its own bounding box.

    For zoom levels with many tiles (>100K), uses coarser grouping to keep
    the query fast.
    """
    tile_count = conn.execute(
        "SELECT COUNT(*) FROM tiles WHERE zoom_level = ?", (z,)
    ).fetchone()[0]

    if tile_count == 0:
        return []

    # For small tile counts or low zoom levels, one bbox is fine
    if tile_count < 500 or z < 10:
        row = conn.execute(
            "SELECT MIN(tile_column), MAX(tile_column), "
            "MIN(tile_row), MAX(tile_row) "
            "FROM tiles WHERE zoom_level = ?", (z,)
        ).fetchone()
        return [_tile_bounds_tms(z, row[0], row[1], row[2], row[3])]

    # Group tiles by row bands and detect gaps
    band_size = max(1, 2 ** max(0, z - 14))  # coarser bands at higher zooms
    bands = conn.execute(
        "SELECT tile_row / ? as band, "
        "MIN(tile_column), MAX(tile_column), "
        "MIN(tile_row), MAX(tile_row) "
        "FROM tiles WHERE zoom_level = ? "
        "GROUP BY band ORDER BY band",
        (band_size, z)
    ).fetchall()

    if not bands:
        return []

    # Merge consecutive bands into clusters, splitting on gaps
    clusters = []
    cur_min_x, cur_max_x = bands[0][1], bands[0][2]
    cur_min_y, cur_max_y = bands[0][3], bands[0][4]
    prev_band = bands[0][0]

    for band, min_x, max_x, min_y, max_y in bands[1:]:
        if band - prev_band > gap_threshold:
            # Gap detected — emit current cluster, start new one
            clusters.append(_tile_bounds_tms(z, cur_min_x, cur_max_x, cur_min_y, cur_max_y))
            cur_min_x, cur_max_x = min_x, max_x
            cur_min_y, cur_max_y = min_y, max_y
        else:
            # Extend current cluster
            cur_min_x = min(cur_min_x, min_x)
            cur_max_x = max(cur_max_x, max_x)
            cur_min_y = min(cur_min_y, min_y)
            cur_max_y = max(cur_max_y, max_y)
        prev_band = band

    clusters.append(_tile_bounds_tms(z, cur_min_x, cur_max_x, cur_min_y, cur_max_y))
    return clusters


def _build_imagery_catalog(
    data_dir: Path,
    tileserver_config: dict | None = None,
) -> list[dict]:
    """Scan data_dir for imagery*.mbtiles and return structured catalog."""
    from datetime import datetime, timezone
    results = []
    for mbt_path in sorted(data_dir.glob("imagery*.mbtiles")):
        source_id = mbt_path.stem
        try:
            conn = sqlite3.connect(
                f"file:{mbt_path}?mode=ro", uri=True, timeout=5
            )
        except sqlite3.OperationalError:
            continue

        try:
            rows = conn.execute(
                "SELECT zoom_level, COUNT(*) as tile_count, "
                "MIN(tile_column), MAX(tile_column), "
                "MIN(tile_row), MAX(tile_row) "
                "FROM tiles GROUP BY zoom_level ORDER BY zoom_level"
            ).fetchall()
        except sqlite3.DatabaseError:
            conn.close()
            continue

        zoom_levels = []
        for z, count, min_x, max_x, min_y, max_y in rows:
            clusters = _cluster_tile_bounds(conn, z)
            zoom_levels.append({
                "zoom": z,
                "tile_count": count,
                "bounds_lonlat": _tile_bounds_tms(z, min_x, max_x, min_y, max_y),
                "clusters": clusters,
            })
        conn.close()

        registered = False
        if tileserver_config and "data" in tileserver_config:
            registered = source_id in tileserver_config["data"]

        stat_info = mbt_path.stat()
        results.append({
            "id": source_id,
            "file": mbt_path.name,
            "size_bytes": stat_info.st_size,
            "modified": datetime.fromtimestamp(stat_info.st_mtime, tz=timezone.utc).isoformat(),
            "registered": registered,
            "zoom_levels": zoom_levels,
        })

    return results


@app.get("/admin/imagery/catalog")
async def imagery_catalog():
    """Return structured catalog of all imagery MBTiles files."""
    data_dir = Path(os.environ.get("DATA_DIR", "/data"))

    ts_config = None
    ts_config_path = os.environ.get("TILESERVER_CONFIG")
    if ts_config_path:
        try:
            ts_config = json.loads(Path(ts_config_path).read_text())
        except (OSError, json.JSONDecodeError):
            pass

    sources = _build_imagery_catalog(data_dir, tileserver_config=ts_config)
    return {"sources": sources}


@app.delete("/admin/imagery/{source_id}", dependencies=[Depends(require_config_source)])
async def delete_imagery_source(source_id: str):
    """Delete an imagery MBTiles file by source ID."""
    if not re.fullmatch(r"imagery[a-z0-9_]*", source_id):
        return JSONResponse(status_code=422, content={"detail": f"Invalid source_id: {source_id}"})

    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    mbt_path = data_dir / f"{source_id}.mbtiles"

    if not mbt_path.exists():
        return JSONResponse(status_code=404, content={"detail": f"File not found: {source_id}.mbtiles"})

    mbt_path.unlink()

    ts_config_path = os.environ.get("TILESERVER_CONFIG")
    if ts_config_path:
        try:
            from tileserver_config import remove_mbtiles_from_config
            remove_mbtiles_from_config(Path(ts_config_path), source_id)
        except Exception:
            pass

    return {"deleted": source_id, "file": f"{source_id}.mbtiles"}


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
@app.post("/admin/credentials", dependencies=[Depends(require_config_source)])
async def save_credentials(body: CredentialBody):
    """Store API credentials in system keyring via keyring agent."""
    has_m2m = body.m2m_username.strip() and body.m2m_token.strip()
    has_copernicus = body.copernicus_username.strip() and body.copernicus_password.strip()

    if not has_m2m and not has_copernicus:
        raise HTTPException(status_code=422, detail="Provide m2m_username+m2m_token and/or copernicus_username+copernicus_password")

    if has_m2m:
        if not keyring_client.store_credential("m2m", "username", body.m2m_username):
            raise HTTPException(status_code=500, detail="Failed to store M2M username in keyring")
        if not keyring_client.store_credential("m2m", "token", body.m2m_token):
            raise HTTPException(status_code=500, detail="Failed to store M2M token in keyring")
    if has_copernicus:
        if not keyring_client.store_credential("copernicus", "username", body.copernicus_username):
            raise HTTPException(status_code=500, detail="Failed to store Copernicus username in keyring")
        if not keyring_client.store_credential("copernicus", "password", body.copernicus_password):
            raise HTTPException(status_code=500, detail="Failed to store Copernicus password in keyring")

    return {"status": "saved"}


@app.get("/admin/credentials/status")
async def credentials_status():
    """Check if credentials are configured (no auth required)."""
    status = keyring_client.get_status()
    return {
        "m2m_configured": status.get("m2m_configured", False),
        "copernicus_configured": status.get("copernicus_configured", False),
        "keyring_available": status.get("keyring_available", False),
    }


@app.delete("/admin/credentials", dependencies=[Depends(require_config_source)])
async def delete_credentials():
    """Remove all stored credentials from keyring."""
    keyring_client.delete_credentials("m2m")
    keyring_client.delete_credentials("copernicus")
    return {"status": "deleted"}


@app.delete("/admin/credentials/m2m", dependencies=[Depends(require_config_source)])
async def delete_m2m_credentials():
    """Remove only M2M credentials from keyring, preserving Copernicus."""
    keyring_client.delete_credentials("m2m")
    return {"status": "deleted"}


@app.delete("/admin/credentials/copernicus", dependencies=[Depends(require_config_source)])
async def delete_copernicus_credentials():
    """Remove only Copernicus credentials from keyring, preserving M2M."""
    keyring_client.delete_credentials("copernicus")
    return {"status": "deleted"}


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
    if pipeline_type == "import":
        return DATA_DIR / ".import-state.json"
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
    is_noaa = body.type == "imagery" and body.mode == "noaa"
    is_sentinel = body.type == "sentinel"
    is_naip = body.type == "naip"

    # Sentinel validation: requires bbox and Copernicus credentials
    if is_sentinel:
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for sentinel")
        cred_status = keyring_client.get_status()
        if not cred_status.get("copernicus_configured"):
            raise HTTPException(status_code=422, detail="Copernicus credentials not configured. POST to /admin/credentials first.")

    # NAIP validation: requires bbox only
    if is_naip:
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for naip")

    if body.type in ("imagery", "elevation"):
        if not body.mode or body.mode not in ("direct", "m2m", "nationalmap", "noaa"):
            raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")
        if not body.bbox:
            raise HTTPException(status_code=422, detail="bbox is required for imagery/elevation")
        if not is_m2m and not is_noaa and not body.zoom:
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

        # Estimate tile count and check disk space (skip for M2M/NOAA — auto-detected or GeoTIFF-based)
        if not is_m2m and not is_noaa:
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
        cred_status = keyring_client.get_status()
        if not cred_status.get("m2m_configured"):
            raise HTTPException(status_code=422, detail="M2M credentials not configured. POST to /admin/credentials first.")

    async with _pipeline_lock:
        client = _get_docker_client()
        if not client:
            raise HTTPException(status_code=503, detail="Docker socket not available")

        session_id = None
        secret_types = []
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
                    if body.counties:
                        command.append(f"--counties={body.counties}")
                elif body.mode == "nationalmap":
                    command = [
                        "python3", "/scripts/acquire_imagery.py",
                        "--mode", "nationalmap",
                        f"--bbox={body.bbox}",
                        f"--zoom={body.zoom or '15-18'}",
                        "--concurrency", str(min(body.concurrency, 20)),
                        "--output", "/data/imagery_naip.mbtiles",
                    ]
                elif body.mode == "noaa":
                    command = [
                        "python3", "/scripts/acquire_imagery.py",
                        "--mode", "noaa",
                        "--output", "/data/imagery_noaa.mbtiles",
                    ]
                    if body.state:
                        # State-mode: let the CLI's argparse type= normalizer handle
                        # USPS → slug translation (existing frontend may send "AZ";
                        # Task 17's _normalize_state_arg emits a deprecation warning
                        # but accepts it).
                        command.append(f"--state={body.state}")
                    else:
                        command.append(f"--bbox={body.bbox}")
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
                "GDAL_CACHEMAX": "64",
                "PYTHONUNBUFFERED": "1",
            }

            # Prepare credentials via keyring agent (tmpfs secrets)
            session_id = f"pipeline-{int(time.time())}"
            secret_types = []
            if body.mode == "m2m":
                secret_types.append("m2m")
            if is_sentinel:
                secret_types.append("copernicus")

            secret_path = None
            if secret_types:
                secret_path = keyring_client.prepare_secrets(secret_types, session_id)
                if not secret_path:
                    raise HTTPException(status_code=500, detail="Failed to prepare credentials from keyring")

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
            if secret_path:
                volumes["/run/geographica/secrets"] = {"bind": "/secrets", "mode": "ro"}

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
                mem_limit="4g",
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
            if secret_types and session_id:
                keyring_client.cleanup_secrets(session_id)
            client.close()

    return {"status": "started"}


@app.get("/admin/pipeline/status")
async def pipeline_status(type: str = Query("imagery", description="Pipeline type: imagery, elevation, osm_poi, sentinel, naip, or import")):
    """Get current pipeline job status (no auth required)."""
    if type not in ("imagery", "elevation", "osm_poi", "sentinel", "naip", "import"):
        raise HTTPException(status_code=422, detail="type must be 'imagery', 'elevation', 'osm_poi', 'sentinel', 'naip', or 'import'")

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

        # Reconcile + TileServer handoff.
        #
        # Two paths enter this block:
        #  1. Crash path: state says "running"/"cancelling" but container is
        #     dead — classify the exit from log markers, then hand off to
        #     TileServer if it looks like a completion.
        #  2. Clean-terminal path: pipeline wrote "completed"/"completed_partial"
        #     itself before exit (via update_progress), and the poll happens
        #     after the container is gone — hand off once, idempotently.
        #
        # The clean-terminal path is the common case. Prior to the
        # `tileserver_restarted_at` stamp, this branch only fired on crashes;
        # clean completions never restarted TileServer, and the map never
        # picked up new tiles until a manual reload (2026-04-17 Bug 1).
        status = state_data.get("status")
        already_handed_off = bool(state_data.get("tileserver_restarted_at"))
        is_crash_path = status in ("running", "cancelling") and not container_running
        is_clean_terminal = (
            status in ("completed", "completed_partial")
            and not container_running
            and not already_handed_off
        )

        if is_crash_path or is_clean_terminal:
            from datetime import datetime, timezone as tz

            if is_crash_path:
                # Stamp crash-recovery diagnostics
                state_data["completed_at"] = datetime.now(tz.utc).isoformat()
                if state_data.get("started_at"):
                    started = datetime.fromisoformat(state_data["started_at"])
                    state_data["duration_seconds"] = int(
                        (datetime.now(tz.utc) - started).total_seconds()
                    )

                # Capture last logs from dead container (client still open)
                if client:
                    try:
                        containers = client.containers.list(
                            all=True, filters={"name": "geographica-pipeline"}
                        )
                        if containers:
                            logs = containers[0].logs(tail=50, timestamps=False).decode("utf-8", errors="replace")
                            state_data["last_logs"] = logs[-2000:]  # cap at 2KB
                    except Exception:
                        pass

                # Determine final status from logs before marking interrupted
                if status == "cancelling":
                    new_status = "cancelled"
                elif any(s in (state_data.get("last_logs") or "") for s in (
                    "MBTiles written to",
                    "NOAA pipeline complete",
                    "Import complete",
                    "pipeline complete",
                )):
                    new_status = "completed"
                else:
                    new_status = "interrupted"
                state_data["status"] = new_status
            else:
                # Clean-terminal path: keep the status the script already wrote
                new_status = status

            # On successful completion: WAL checkpoint + TileServer restart.
            # The pipeline writes to MBTiles in WAL mode. TileServer caches
            # metadata at startup and won't see new tiles/bounds without a
            # restart. This is the centralized handoff point.
            if new_status in ("completed", "completed_partial") and client:
                # B14: WAL-checkpoint the MBTiles that matches this
                # pipeline's `type`. The pipeline already checkpointed at
                # exit; this is a safety net for crashes and a no-op after
                # a clean exit. We keep WAL mode (D3) — flipping to DELETE
                # can fail against TileServer's live read-lock.
                mbtiles_file = _mbtiles_path_for_type(type)
                if mbtiles_file.exists():
                    try:
                        import sqlite3 as _wal
                        with _wal.connect(str(mbtiles_file), timeout=5) as _wc:
                            _wc.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                        print(f"WAL checkpoint: {mbtiles_file.name}", flush=True)
                    except Exception as exc:
                        print(f"WAL checkpoint failed for {mbtiles_file.name}: {exc}", flush=True)

                # Restart TileServer to pick up new metadata/bounds
                try:
                    ts_containers = client.containers.list(
                        all=False, filters={"name": "geographica-tileserver"}
                    )
                    for ts in ts_containers:
                        if ts.status == "running":
                            ts.restart(timeout=30)
                            print("TileServer restarted after pipeline completion", flush=True)
                except Exception as exc:
                    print(f"TileServer restart failed: {exc}", flush=True)

                # Stamp handoff regardless of whether a TileServer was found
                # or the restart call raised — next poll must be a no-op
                # rather than retry-spamming Docker every 10s forever.
                state_data["tileserver_restarted_at"] = datetime.now(tz.utc).isoformat()

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
            _state_file_for_type("import"),
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
            containers = client.containers.list(
                all=False, filters={"name": "geographica-pipeline"}
            )
            print(f"Cancel: found {len(containers)} pipeline containers", flush=True)
            for container in containers:
                print(f"Cancel: container {container.name} status={container.status}", flush=True)
                if container.status == "running":
                    print(f"Stopping pipeline container: {container.name}", flush=True)
                    container.stop(timeout=60)
                    print(f"Pipeline container stopped: {container.name}", flush=True)
        except Exception as exc:
            print(f"Cancel: failed to stop pipeline container: {exc}", flush=True)
        finally:
            client.close()

    return {"status": "cancelling"}


@app.get("/admin/pipeline/import/scan", dependencies=[Depends(require_config_source)])
async def import_scan():
    """Scan import directory for GeoTIFF files."""
    import_dir = DATA_DIR / "import"
    if not import_dir.exists():
        import_dir.mkdir(parents=True)
        return {"tif_count": 0, "total_bytes": 0, "other_geo_count": 0}

    tif_files = []
    other_geo = []
    total_bytes = 0
    other_extensions = {".jp2", ".sid", ".img", ".ecw"}

    dirs = [import_dir]
    for item in import_dir.iterdir():
        if item.is_dir() and not item.is_symlink():
            dirs.append(item)

    for d in dirs:
        for f in d.iterdir():
            if f.is_symlink() or not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in (".tif", ".tiff"):
                tif_files.append(f)
                total_bytes += f.stat().st_size
            elif ext in other_extensions:
                other_geo.append(f)

    return {
        "tif_count": len(tif_files),
        "total_bytes": total_bytes,
        "other_geo_count": len(other_geo),
    }


def _load_noaa_catalog(data_dir: Path) -> "tuple[dict | None, Path | None]":
    """Load the pinned catalog snapshot via the noaa_naip_catalog.json symlink.

    Returns (catalog_dict, resolved_snapshot_path) on success, or (None, None)
    when the symlink is absent or the file cannot be parsed.
    """
    symlink = data_dir / "noaa_naip_catalog.json"
    if not symlink.exists():
        return (None, None)
    try:
        snapshot_path = symlink.resolve(strict=True)
        catalog = json.loads(snapshot_path.read_text())
        return (catalog, snapshot_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"WARNING: Failed to load NOAA catalog: {exc}", flush=True)
        return (None, None)


@app.get("/admin/pipeline/noaa/estimate", dependencies=[Depends(require_config_source)])
async def noaa_estimate(
    bbox: str = Query(..., description="west,south,east,north"),
    state: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
):
    """Estimate NOAA NAIP download size and time for a given bbox.

    Supports two modes:
    - State mode: ``state=AZ`` (USPS) or ``state=arizona`` (slug). ``year`` is
      accepted but ignored — the catalog is keyed by slug only.
    - Bbox mode: omit ``state``; the endpoint resolves all states that both
      intersect the bbox AND appear in the catalog.

    Returns all legacy fields (``tile_count``, ``raw_download_gb``, etc.) plus
    the new Task-19 fields: ``states``, ``missing``, ``placename``,
    ``catalog_snapshot``, ``intermediate_gb``, ``peak_required_gb``.
    """
    import struct

    NOAA_TILE_SIZE_MB = 486

    # ------------------------------------------------------------------
    # 1. Load catalog from snapshot (replaces the hard-coded dict)
    # ------------------------------------------------------------------
    catalog, snapshot_path = _load_noaa_catalog(DATA_DIR)
    if catalog is None:
        return {
            "status": "no_catalog",
            "message": "Run refresh_catalog to populate the NOAA catalog.",
        }

    entries: dict[str, dict] = catalog.get("entries", {})

    # ------------------------------------------------------------------
    # 2. Resolve which slugs to use (state mode vs bbox mode)
    # ------------------------------------------------------------------
    # Normalise the ``state`` query param: accept USPS (AZ) or slug (arizona).
    # ``year`` is deprecated — accepted for backward compat, silently ignored.
    if state is not None:
        state_upper = state.upper()
        if state_upper in SLUG_BY_USPS:
            slug = SLUG_BY_USPS.get(state_upper)
        else:
            # Assume it's already a slug
            slug = state.lower()

        if slug is None:
            raise HTTPException(
                status_code=422,
                detail=f"State {state!r} is not supported (Alaska and Hawaii are excluded).",
            )

        if slug not in entries:
            # Catalog present but this state isn't cataloged → no_index
            return {
                "status": "no_index",
                "message": f"State {slug!r} is not in the current catalog snapshot. "
                           "Run refresh_catalog to update.",
            }

        states_list: list[str] = [slug]
        # In single-state mode, missing[] is empty — the state IS in the catalog.
        missing_list: list[str] = []

    else:
        # Bbox mode: find all states that intersect the bbox, split into
        # cataloged (states_list) and not-yet-cataloged (missing_list).
        intersecting = states_intersecting(bbox)
        states_list = [s for s in intersecting if s in entries]
        missing_list = [s for s in intersecting if s not in entries]

        if not states_list:
            return {
                "status": "no_index",
                "message": "No cataloged states intersect the provided bbox. "
                           "Run refresh_catalog to update the catalog.",
            }

    # ------------------------------------------------------------------
    # 3. Validate bbox
    # ------------------------------------------------------------------
    try:
        parts = [float(x.strip()) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError("need 4 values")
        west, south, east, north = parts
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid bbox: {e}")

    # ------------------------------------------------------------------
    # 4. Tile count — sum across all cataloged states in this estimate.
    #    Use the catalog's tile_count per state; spatial filtering via
    #    shapefile cache stays as-is when the tile index is available.
    #    Fall back to catalog tile_count when shapefile isn't cached.
    # ------------------------------------------------------------------
    total_tile_count = 0
    for slug in states_list:
        entry = entries[slug]
        catalog_tile_count: int = entry.get("tile_count", 0)

        # Check for a cached shapefile (legacy path; preserves per-bbox filtering)
        usps = entry.get("usps", slug.upper()[:2])
        entry_year = entry.get("year", 2021)
        cache = DATA_DIR / "noaa_cache" / f"{usps}_{entry_year}"
        shp_files = list(cache.glob("*.shp")) if cache.exists() else []

        if shp_files:
            dbf_path = shp_files[0].with_suffix(".dbf")
            state_tile_count = 0
            try:
                with open(dbf_path, "rb") as f:
                    f.read(4)
                    total_records = struct.unpack("<I", f.read(4))[0]
                # Estimate tile fraction via bbox overlap with state extent
                from scripts.common.state_bboxes import STATE_BBOXES
                state_bbox = STATE_BBOXES.get(slug)
                if state_bbox:
                    sw, ss, se, sn = state_bbox
                    state_area = (se - sw) * (sn - ss)
                    uw = min(east, se) - max(west, sw)
                    uh = min(north, sn) - max(south, ss)
                    if uw > 0 and uh > 0 and state_area > 0:
                        ratio = min(1.0, (uw * uh) / state_area)
                        state_tile_count = int(total_records * ratio)
                    else:
                        state_tile_count = 0
                else:
                    state_tile_count = total_records
            except (OSError, struct.error):
                state_tile_count = catalog_tile_count
        else:
            # No shapefile cache — use catalog total
            state_tile_count = catalog_tile_count

        total_tile_count += state_tile_count

    tile_count = total_tile_count

    # ------------------------------------------------------------------
    # 5. Derived cost estimates (same economics as before)
    # ------------------------------------------------------------------
    raw_download_gb = tile_count * NOAA_TILE_SIZE_MB / 1024
    final_mbtiles_gb = tile_count * 29 / 1024  # empirical: ~29 MB/tile in MBTiles

    download_concurrency = 4
    reproject_workers = 4
    download_per_tile_s = (NOAA_TILE_SIZE_MB / 3.0) / download_concurrency  # ~40 s
    reproject_per_tile_s = 45 / reproject_workers                            # ~11 s
    merge_per_tile_s = 20                                                     # serial bottleneck
    effective_per_tile_s = max(download_per_tile_s, reproject_per_tile_s, merge_per_tile_s)
    startup_overhead_s = 120
    est_seconds = tile_count * effective_per_tile_s + startup_overhead_s
    est_hours = est_seconds / 3600

    return {
        # ---- legacy fields (unchanged semantics) ----
        "status": "ok",
        "tile_count": tile_count,
        "raw_download_gb": round(raw_download_gb, 1),
        "final_mbtiles_gb": round(final_mbtiles_gb, 1),
        "staging_peak_gb": round(NOAA_TILE_SIZE_MB * (download_concurrency + 1) / 1024, 1),
        "est_hours": round(est_hours, 2),
        "est_days": round(est_hours / 24, 2),
        "per_tile_seconds": round(effective_per_tile_s, 1),
        "download_concurrency": download_concurrency,
        "download_speed_mbs": 3.0,
        "disk_free_gb": round(_get_disk_free_gb(), 1),
        # ---- new fields (Task 19) ----
        "states": states_list,
        "missing": missing_list,
        "placename": None,           # Task 21 fills this in
        "catalog_snapshot": str(snapshot_path),
        "intermediate_gb": 0.0,      # Task 20 fills this in
        "peak_required_gb": 0.0,     # Task 20 fills this in
    }


@app.post("/admin/pipeline/import", dependencies=[Depends(require_config_source)])
async def pipeline_import(
    layer_name: Optional[str] = Query(None),
    delete_after: bool = Query(False),
):
    """Start a BYO GeoTIFF import pipeline."""
    import_dir = DATA_DIR / "import"
    if not import_dir.exists():
        import_dir.mkdir(parents=True)

    # Quick scan to verify files exist
    tif_count = sum(
        1 for d in [import_dir] + [x for x in import_dir.iterdir() if x.is_dir() and not x.is_symlink()]
        for f in d.iterdir()
        if f.is_file() and not f.is_symlink() and f.suffix.lower() in (".tif", ".tiff")
    )
    if tif_count == 0:
        raise HTTPException(status_code=422, detail="No GeoTIFF files found in import directory")

    async with _pipeline_lock:
        client = _get_docker_client()
        if not client:
            raise HTTPException(status_code=503, detail="Docker socket not available")

        try:
            if _is_pipeline_container_running(client):
                raise HTTPException(status_code=409, detail="A pipeline job is already running")

            command = [
                "python3", "/scripts/import_imagery.py",
                "--input", "/data/import",
                "--output-dir", "/data",
            ]
            if layer_name:
                command.extend(["--name", layer_name])
            if delete_after:
                command.append("--delete-after")

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
                raise HTTPException(status_code=500, detail="Cannot determine host data path")

            volumes = {host_data_path: {"bind": "/data", "mode": "rw"}}
            if host_scripts_path:
                volumes[host_scripts_path] = {"bind": "/scripts", "mode": "ro"}

            try:
                old = client.containers.get("geographica-pipeline")
                old.remove(force=True)
            except Exception:
                pass

            env = {"GDAL_CACHEMAX": "512", "PYTHONUNBUFFERED": "1"}

            try:
                networks = client.networks.list(names=["geographica_default"])
                network = networks[0].name if networks else "bridge"
            except Exception:
                network = "bridge"

            container = client.containers.run(
                "geographica-pipeline",
                command=command,
                name="geographica-pipeline",
                detach=True,
                remove=False,
                volumes=volumes,
                environment=env,
                network=network,
                mem_limit="4g",
            )

            from datetime import datetime, timezone as tz
            state_data = {
                "status": "running",
                "type": "import",
                "source": "import",
                "container_id": container.id,
                "started_at": datetime.now(tz.utc).isoformat(),
            }
            state_file = DATA_DIR / ".import-state.json"
            state_file.write_text(json.dumps(state_data, indent=2))

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start import: {e}")
        finally:
            client.close()

    return {"status": "started", "files": tif_count}


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
