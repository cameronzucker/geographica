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
    m2m_username: str
    m2m_token: str


class PipelineStartBody(BaseModel):
    type: str  # "imagery" or "elevation"
    mode: str  # "direct" or "m2m"
    bbox: str  # "west,south,east,north"
    zoom: str  # "min-max"
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
    if zoom_min < 0 or zoom_max > 18 or zoom_min > zoom_max:
        raise ValueError("zoom values must be 0-18 with min <= max")
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
    http_client: Optional[httpx.AsyncClient] = None


state = State()


async def _open_poi_db() -> None:
    """Try to open the POI SQLite database.  Fail silently if it doesn't exist."""
    try:
        conn = await aiosqlite.connect(POI_DB_PATH, uri=False)
        conn.row_factory = aiosqlite.Row
        # Quick sanity check that the expected tables exist.
        async with conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='poi_fts'"
        ) as cur:
            row = await cur.fetchone()
            if row is None:
                await conn.close()
                state.poi_db = None
                state.poi_db_loaded = False
                return
        state.poi_db = conn
        state.poi_db_loaded = True
    except Exception:
        state.poi_db = None
        state.poi_db_loaded = False


@asynccontextmanager
async def lifespan(_app: FastAPI):
    state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
    await _open_poi_db()
    yield
    # Shutdown
    if state.http_client:
        await state.http_client.aclose()
    if state.poi_db:
        await state.poi_db.close()


app = FastAPI(title="Geographica Search", lifespan=lifespan)


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
# Deduplication
# ---------------------------------------------------------------------------
def _deduplicate(
    nominatim_results: list[dict],
    poi_results: list[dict],
) -> list[dict]:
    """Merge results, dropping POI entries within 100 m of any Nominatim result."""
    merged = list(nominatim_results)
    for poi in poi_results:
        dominated = False
        for nom in nominatim_results:
            try:
                dist = haversine_m(poi["lat"], poi["lon"], nom["lat"], nom["lon"])
                if dist <= 100:
                    dominated = True
                    break
            except (KeyError, TypeError, ValueError):
                continue
        if not dominated:
            merged.append(poi)
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

    nominatim_results, poi_results = await asyncio.gather(
        nominatim_task, poi_task, return_exceptions=True
    )

    # If either leg raised, treat as empty.
    if isinstance(nominatim_results, BaseException):
        nominatim_results = []
    if isinstance(poi_results, BaseException):
        poi_results = []

    merged = _deduplicate(nominatim_results, poi_results)
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


@app.get("/admin/status")
async def admin_status():
    """Return status of all Geographica services and long-running tasks."""
    client = _get_docker_client()
    if not client:
        return {"error": "Docker socket not available", "services": []}

    services = []
    try:
        containers = client.containers.list(all=True, filters={"name": "geographica-"})
        for c in sorted(containers, key=lambda x: x.name):
            svc = {
                "name": c.name.replace("geographica-", ""),
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
    except Exception as e:
        return {"error": str(e), "services": []}
    finally:
        client.close()

    # Check for data pipeline files (downloads in progress)
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

    return {"services": services, "data_tasks": data_tasks}


# ---------------------------------------------------------------------------
# Credential management
# ---------------------------------------------------------------------------
@app.post("/admin/credentials", dependencies=[Depends(require_config_source)])
async def save_credentials(body: CredentialBody):
    """Store M2M API credentials securely."""
    if not body.m2m_username.strip() or not body.m2m_token.strip():
        raise HTTPException(status_code=422, detail="Both m2m_username and m2m_token must be non-empty")

    cred_data = json.dumps({
        "m2m_username": body.m2m_username,
        "m2m_token": body.m2m_token,
    })

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
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {e}")

    return {"status": "saved"}


@app.get("/admin/credentials/status")
async def credentials_status():
    """Check if credentials are configured (no auth required)."""
    return {"m2m_configured": CREDENTIALS_PATH.exists()}


@app.delete("/admin/credentials", dependencies=[Depends(require_config_source)])
async def delete_credentials():
    """Remove stored credentials."""
    try:
        CREDENTIALS_PATH.unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete credentials: {e}")
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------
def _state_file_for_type(pipeline_type: str) -> Path:
    """Return the state file path for a given pipeline type."""
    if pipeline_type == "elevation":
        return DATA_DIR / ".elevation-state.json"
    return DATA_DIR / ".pipeline-state.json"


def _mbtiles_path_for_type(pipeline_type: str) -> Path:
    """Return the mbtiles output path for a given pipeline type."""
    if pipeline_type == "elevation":
        return DATA_DIR / "elevation.mbtiles"
    return DATA_DIR / "imagery.mbtiles"


def _script_for_type(pipeline_type: str) -> str:
    """Return the script path for a given pipeline type."""
    if pipeline_type == "elevation":
        return "/scripts/download_elevation.py"
    return "/scripts/acquire_imagery.py"


def _is_pipeline_container_running(client) -> bool:
    """Check if the pipeline container is currently running."""
    try:
        container = client.containers.get("geographica-pipeline")
        return container.status == "running"
    except Exception:
        return False


def _get_disk_free_gb() -> float:
    """Return free disk space in GB for the /data partition."""
    usage = shutil.disk_usage(str(DATA_DIR))
    return usage.free / (1024 ** 3)


@app.post("/admin/pipeline/start", dependencies=[Depends(require_config_source)])
async def pipeline_start(body: PipelineStartBody):
    """Start an imagery or elevation download pipeline."""
    # Validate type
    if body.type not in ("imagery", "elevation"):
        raise HTTPException(status_code=422, detail="type must be 'imagery' or 'elevation'")
    if body.mode not in ("direct", "m2m"):
        raise HTTPException(status_code=422, detail="mode must be 'direct' or 'm2m'")

    # Parse and validate bbox
    try:
        bbox = _parse_bbox(body.bbox)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid bbox: {e}")

    # Parse and validate zoom
    try:
        zoom_min, zoom_max = _parse_zoom(body.zoom)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid zoom: {e}")

    # Estimate tile count and check disk space
    tile_count = estimate_tile_count(bbox, zoom_min, zoom_max)
    # Rough estimate: ~20 KB per tile average (measured from USGS imagery)
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

            # Handle existing mbtiles if not updating
            mbtiles_path = _mbtiles_path_for_type(body.type)
            if not body.update and mbtiles_path.exists():
                prev_path = mbtiles_path.with_suffix(".mbtiles.prev")
                try:
                    os.replace(str(mbtiles_path), str(prev_path))
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Failed to rename existing file: {e}")

            # Build command
            script = _script_for_type(body.type)
            command = [
                "python3", script,
                "--mode", body.mode,
                f"--bbox={body.bbox}",
                f"--zoom={body.zoom}",
                "--concurrency", str(body.concurrency),
                "--output", f"/data/{mbtiles_path.name}",
            ]

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
            state_data = {
                "status": "running",
                "type": body.type,
                "mode": body.mode,
                "bbox": body.bbox,
                "zoom": body.zoom,
                "concurrency": body.concurrency,
                "update": body.update,
                "estimated_tiles": tile_count,
                "container_id": container.id,
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
async def pipeline_status(type: str = Query("imagery", description="Pipeline type: imagery or elevation")):
    """Get current pipeline job status (no auth required)."""
    if type not in ("imagery", "elevation"):
        raise HTTPException(status_code=422, detail="type must be 'imagery' or 'elevation'")

    state_file = _state_file_for_type(type)
    state_data = {}
    if state_file.exists():
        try:
            state_data = json.loads(state_file.read_text())
        except (json.JSONDecodeError, OSError):
            state_data = {"status": "unknown", "error": "Could not read state file"}

    # Check container status
    client = _get_docker_client()
    container_running = False
    if client:
        try:
            container_running = _is_pipeline_container_running(client)
        except Exception:
            pass
        finally:
            client.close()

    # Reconcile: if state says running but container is dead, mark interrupted
    # and capture last logs for crash diagnosis
    if state_data.get("status") in ("running", "cancelling") and not container_running:
        new_status = "cancelled" if state_data.get("status") == "cancelling" else "interrupted"
        state_data["status"] = new_status

        # Try to capture last logs from dead container (if it wasn't auto-removed)
        if client:
            try:
                container = client.containers.get("geographica-pipeline")
                logs = container.logs(tail=50, timestamps=False).decode("utf-8", errors="replace")
                state_data["last_logs"] = logs[-2000:]  # cap at 2KB
            except Exception:
                pass

        try:
            tmp = state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state_data, indent=2))
            os.replace(str(tmp), str(state_file))
        except OSError:
            pass

    # Add live fields
    state_data["container_running"] = container_running

    # Calculate estimated tiles if bbox/zoom available
    if "bbox" in state_data and "zoom" in state_data:
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
        # Write "cancelling" to both possible state files immediately
        for state_file in [
            Path("/data/.pipeline-state.json"),
            Path("/data/.elevation-state.json"),
        ]:
            if state_file.exists():
                try:
                    existing = json.loads(state_file.read_text())
                    if existing.get("status") == "running":
                        existing["status"] = "cancelling"
                        tmp = state_file.with_suffix(".json.tmp")
                        tmp.write_text(json.dumps(existing))
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
