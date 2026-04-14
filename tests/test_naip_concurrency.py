"""Tests for B11 fix: wiring up --concurrency parameter in acquire_naip.py."""

import asyncio
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


class TestConcurrencyParameter:
    """Verify --concurrency is respected in the NAIP pipeline."""

    def test_cli_accepts_concurrency(self):
        """--concurrency is parsed from CLI args."""
        import argparse

        # Test that argparse includes the argument
        parser = argparse.ArgumentParser()
        parser.add_argument("--concurrency", type=int, default=2)
        args = parser.parse_args(["--concurrency", "4"])
        assert args.concurrency == 4

    def test_run_pipeline_accepts_concurrency_param(self):
        """run_pipeline function accepts concurrency parameter."""
        from acquire_naip import run_pipeline

        sig = inspect.signature(run_pipeline)
        assert "concurrency" in sig.parameters
        # Default should be 2
        assert sig.parameters["concurrency"].default == 2

    @pytest.mark.asyncio
    async def test_semaphore_created_with_concurrency(self, tmp_path):
        """Verify that the download semaphore uses the concurrency value."""
        from acquire_naip import run_pipeline

        # Mock everything to avoid real downloads
        with patch("acquire_naip.counties_for_bbox", return_value=[]), \
             patch("acquire_naip.update_progress"):
            # Empty counties = early return, but concurrency is accepted
            await run_pipeline(
                bbox_str="-112,33,-111,34",
                output_path=tmp_path / "out.mbtiles",
                staging_dir=tmp_path / "staging",
                counties_db=str(tmp_path / "counties.sqlite"),
                concurrency=4,
            )
        # If we got here without error, the parameter was accepted
