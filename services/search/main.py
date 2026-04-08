"""Unified search service combining Nominatim geocoding with local POI FTS5 database.

Also hosts the /admin/status endpoint for monitoring long-running tasks
(container health, import progress, download status).
"""

import asyncio
import math
import os
import re
from contextlib import asynccontextmanager
from typing import Optional

import aiosqlite
import httpx
from fastapi import FastAPI, Query

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "http://nominatim:8080")
POI_DB_PATH = os.environ.get("POI_DB_PATH", "/data/poi.sqlite")

EARTH_RADIUS_M = 6_371_000


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

    # Elevation MBTiles
    elev_path = data_dir / "elevation.mbtiles"
    if elev_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(elev_path))
            tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            # Check for checkpoint table
            has_checkpoint = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='_checkpoint'"
            ).fetchone()[0]
            conn.close()
            data_tasks.append({
                "name": "Elevation tiles",
                "tiles": tile_count,
                "status": "downloading" if has_checkpoint else "complete",
            })
        except Exception:
            data_tasks.append({"name": "Elevation tiles", "status": "locked"})

    # Imagery MBTiles
    imagery_path = data_dir / "imagery.mbtiles"
    if imagery_path.exists():
        try:
            import sqlite3
            conn = sqlite3.connect(str(imagery_path))
            tile_count = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
            has_checkpoint = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='_checkpoint'"
            ).fetchone()[0]
            conn.close()
            data_tasks.append({
                "name": "Imagery tiles",
                "tiles": tile_count,
                "status": "downloading" if has_checkpoint else "complete",
            })
        except Exception:
            data_tasks.append({"name": "Imagery tiles", "status": "locked"})

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
