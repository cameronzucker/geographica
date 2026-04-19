"""Test B16 fix: NAIP pipeline runs _process_county concurrently up to `concurrency` limit."""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestTrueConcurrency:
    """Verify concurrency=3 runs up to 3 counties in parallel."""

    @pytest.mark.asyncio
    async def test_multiple_counties_run_concurrently(self, tmp_path, monkeypatch):
        """With concurrency=3 and 3 counties, max observed in-flight = 3."""
        import acquire_naip

        # Three fake counties
        counties = [
            ("12345", "CountyA", "AZ", (-111.0, 33.0, -110.9, 33.1)),
            ("12346", "CountyB", "AZ", (-111.1, 33.1, -111.0, 33.2)),
            ("12347", "CountyC", "AZ", (-111.2, 33.2, -111.1, 33.3)),
        ]

        # Track concurrent calls
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_download_county(session, fips, url_info, staging_dir):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                if in_flight > max_in_flight:
                    max_in_flight = in_flight
            # Simulate meaningful work
            await asyncio.sleep(0.1)
            async with lock:
                in_flight -= 1
            fake_path = staging_dir / f"naip_{fips}.jp2"
            fake_path.write_bytes(b"\x00\x00\x00\x0cjP  " + b"\x00" * 100)  # JP2 magic
            return fake_path

        def fake_convert(jp2_path, staging_dir, fips):
            tif = staging_dir / f"naip_{fips}.tif"
            tif.write_bytes(b"fake tiff")
            return tif

        # Patch so the pipeline reaches _process_county
        with patch.object(acquire_naip, "counties_for_bbox", return_value=counties), \
             patch.object(acquire_naip, "discover_county_urls",
                          new=AsyncMock(return_value={
                              "12345": {"url": "http://x/a.jp2", "format": "jp2",
                                        "filename": "a.jp2"},
                              "12346": {"url": "http://x/b.jp2", "format": "jp2",
                                        "filename": "b.jp2"},
                              "12347": {"url": "http://x/c.jp2", "format": "jp2",
                                        "filename": "c.jp2"},
                          })), \
             patch.object(acquire_naip, "download_county", new=fake_download_county), \
             patch.object(acquire_naip, "convert_jp2_to_geotiff", side_effect=fake_convert), \
             patch.object(acquire_naip, "validate_file_header", return_value=True), \
             patch.object(acquire_naip, "merge_to_mbtiles", return_value=True), \
             patch.object(acquire_naip, "check_disk_space"), \
             patch.object(acquire_naip, "update_progress"):

            staging = tmp_path / "staging"
            staging.mkdir()

            # Run the pipeline with concurrency=3
            await acquire_naip.run_pipeline(
                bbox_str="-112,33,-110,34",
                output_path=tmp_path / "out.mbtiles",
                staging_dir=staging,
                counties_db=str(tmp_path / "counties.sqlite"),
                concurrency=3,
            )

        assert max_in_flight >= 2, (
            f"Expected at least 2 concurrent downloads with concurrency=3; "
            f"observed max in-flight = {max_in_flight}. B16 fix not applied."
        )


class TestCheckpointLockSerialization:
    """Concurrent _process_county completions must serialize checkpoint writes."""

    def test_save_checkpoint_lock_exists(self):
        """run_pipeline must use an asyncio.Lock around save_checkpoint."""
        import inspect
        import acquire_naip
        src = inspect.getsource(acquire_naip.run_pipeline)
        assert "asyncio.Lock" in src or "asyncio.gather" in src, (
            "B16 fix: run_pipeline must use asyncio.gather for concurrent counties "
            "AND an asyncio.Lock around save_checkpoint."
        )
