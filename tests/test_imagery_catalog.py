"""Tests for GET /admin/imagery/catalog endpoint."""

import json
import math
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "search"))


def _create_test_mbtiles(path: Path, tiles: list[tuple[int, int, int]]) -> None:
    """Create a minimal MBTiles file with specified tiles (zoom, col, row)."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
        "tile_row INTEGER, tile_data BLOB, "
        "PRIMARY KEY (zoom_level, tile_column, tile_row))"
    )
    conn.execute("CREATE TABLE metadata (name TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('name', 'test')")
    for z, x, y in tiles:
        conn.execute("INSERT INTO tiles VALUES (?, ?, ?, X'FFD8FF')", (z, x, y))
    conn.commit()
    conn.close()


class TestBuildImageryCatalog:
    def test_catalog_returns_sources(self, tmp_path):
        from main import _build_imagery_catalog
        mbtiles = tmp_path / "imagery_noaa.mbtiles"
        _create_test_mbtiles(mbtiles, [(18, 49513, 157094), (18, 49514, 157094), (15, 6189, 19636)])
        result = _build_imagery_catalog(tmp_path)
        assert len(result) == 1
        src = result[0]
        assert src["id"] == "imagery_noaa"
        assert src["file"] == "imagery_noaa.mbtiles"
        assert src["size_bytes"] > 0
        assert len(src["zoom_levels"]) == 2
        z18 = next(z for z in src["zoom_levels"] if z["zoom"] == 18)
        assert z18["tile_count"] == 2
        z15 = next(z for z in src["zoom_levels"] if z["zoom"] == 15)
        assert z15["tile_count"] == 1

    def test_catalog_bounds_are_valid_lonlat(self, tmp_path):
        from main import _build_imagery_catalog
        mbtiles = tmp_path / "imagery_noaa.mbtiles"
        _create_test_mbtiles(mbtiles, [(18, 49513, 157094)])
        result = _build_imagery_catalog(tmp_path)
        bounds = result[0]["zoom_levels"][0]["bounds_lonlat"]
        lon_min, lat_min, lon_max, lat_max = bounds
        assert -180 <= lon_min < lon_max <= 180
        assert -85 <= lat_min < lat_max <= 85

    def test_catalog_skips_non_imagery_files(self, tmp_path):
        from main import _build_imagery_catalog
        _create_test_mbtiles(tmp_path / "imagery.mbtiles", [(14, 1, 1)])
        _create_test_mbtiles(tmp_path / "elevation.mbtiles", [(10, 1, 1)])
        _create_test_mbtiles(tmp_path / "public-lands.mbtiles", [(8, 1, 1)])
        result = _build_imagery_catalog(tmp_path)
        ids = [s["id"] for s in result]
        assert "imagery" in ids
        assert "elevation" not in ids
        assert "public-lands" not in ids

    def test_catalog_handles_corrupt_mbtiles(self, tmp_path):
        from main import _build_imagery_catalog
        _create_test_mbtiles(tmp_path / "imagery.mbtiles", [(14, 1, 1)])
        (tmp_path / "imagery_broken.mbtiles").write_bytes(b"not a database")
        result = _build_imagery_catalog(tmp_path)
        ids = [s["id"] for s in result]
        assert "imagery" in ids
        assert "imagery_broken" not in ids

    def test_catalog_empty_directory(self, tmp_path):
        from main import _build_imagery_catalog
        result = _build_imagery_catalog(tmp_path)
        assert result == []

    def test_catalog_registered_flag(self, tmp_path):
        from main import _build_imagery_catalog
        _create_test_mbtiles(tmp_path / "imagery_noaa.mbtiles", [(18, 1, 1)])
        ts_config = {"data": {"imagery_noaa": {"mbtiles": "/srv/data/imagery_noaa.mbtiles"}}}
        result = _build_imagery_catalog(tmp_path, tileserver_config=ts_config)
        assert result[0]["registered"] is True
        result2 = _build_imagery_catalog(tmp_path, tileserver_config={"data": {}})
        assert result2[0]["registered"] is False


class TestImageryCatalogEndpoint:
    def test_endpoint_returns_200(self, tmp_path):
        _create_test_mbtiles(tmp_path / "imagery.mbtiles", [(14, 1, 1)])
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.get("/admin/imagery/catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert "sources" in data
        assert len(data["sources"]) == 1
        assert data["sources"][0]["id"] == "imagery"


_CONFIG_HEADERS = {"X-Config-Source": "internal", "X-Geographica": "1"}


class TestDeleteImageryEndpoint:
    def test_delete_existing_source(self, tmp_path):
        mbt = tmp_path / "imagery_test.mbtiles"
        _create_test_mbtiles(mbt, [(14, 1, 1)])
        assert mbt.exists()
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/imagery_test", headers=_CONFIG_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["deleted"] == "imagery_test"
        assert data["file"] == "imagery_test.mbtiles"
        assert not mbt.exists()

    def test_delete_nonexistent_returns_404(self, tmp_path):
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/imagery_nosuch", headers=_CONFIG_HEADERS)
        assert resp.status_code == 404

    def test_delete_rejects_path_traversal(self, tmp_path):
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/../../etc/passwd", headers=_CONFIG_HEADERS)
        assert resp.status_code in (404, 422)

    def test_delete_rejects_non_imagery_id(self, tmp_path):
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/elevation", headers=_CONFIG_HEADERS)
        assert resp.status_code == 422

    def test_delete_accepts_base_imagery(self, tmp_path):
        mbt = tmp_path / "imagery.mbtiles"
        _create_test_mbtiles(mbt, [(14, 1, 1)])
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/imagery", headers=_CONFIG_HEADERS)
        assert resp.status_code == 200
        assert not mbt.exists()

    def test_delete_without_auth_returns_403(self, tmp_path):
        _create_test_mbtiles(tmp_path / "imagery_test.mbtiles", [(18, 1, 1)])
        with patch.dict("os.environ", {"DATA_DIR": str(tmp_path)}):
            from main import app
            from fastapi.testclient import TestClient
            client = TestClient(app)
            resp = client.delete("/admin/imagery/imagery_test")  # no headers
        assert resp.status_code == 403
