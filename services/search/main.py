"""Unified search service combining Nominatim geocoding with local POI FTS5 database."""

import asyncio
import math
import os
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
