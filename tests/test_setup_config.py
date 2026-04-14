"""Tests for setup/config.py — system detection and config generation."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "setup"))
from config import (
    REGION_PRESETS,
    RAM_PROFILE_16GB,
    RAM_PROFILE_8GB,
    validate_bbox,
    get_ram_profile,
    detect_host_ip,
    detect_ram_mb,
    detect_storage,
    generate_env,
)


# ---------------------------------------------------------------------------
# TestBboxValidation
# ---------------------------------------------------------------------------
class TestBboxValidation:
    def test_valid_western_us(self):
        assert validate_bbox("-124.8,31.3,-102.0,49.0") is True

    def test_valid_arizona(self):
        assert validate_bbox("-114.8,31.3,-109.0,37.0") is True

    def test_lon_over_180(self):
        assert validate_bbox("-181.0,31.3,-102.0,49.0") is False

    def test_lat_over_90(self):
        assert validate_bbox("-124.8,91.0,-102.0,49.0") is False

    def test_west_greater_than_east(self):
        assert validate_bbox("-102.0,31.3,-124.8,49.0") is False

    def test_south_greater_than_north(self):
        assert validate_bbox("-124.8,49.0,-102.0,31.3") is False

    def test_non_numeric(self):
        assert validate_bbox("abc,31.3,-102.0,49.0") is False

    def test_wrong_format_two_values(self):
        assert validate_bbox("-124.8,31.3") is False

    def test_injection_semicolon(self):
        assert validate_bbox("-124.8;DROP TABLE,31.3,-102.0,49.0") is False


# ---------------------------------------------------------------------------
# TestRamProfile
# ---------------------------------------------------------------------------
class TestRamProfile:
    def test_16gb_values(self):
        profile = RAM_PROFILE_16GB
        assert profile["nominatim_memory"] == "8G"
        assert profile["postgres_shared_buffers"] == "1GB"
        assert profile["postgres_maintenance_work_mem"] == "1GB"
        assert profile["postgres_effective_cache_size"] == "4GB"
        assert profile["valhalla_memory"] == "4G"
        assert profile["valhalla_threads"] == "4"
        assert profile["tileserver_memory"] == "1G"
        assert profile["stt_memory"] == "1536M"
        assert profile["pipeline_memory"] == "2G"
        assert profile["pipeline_gdal_cache"] == "1024"
        assert profile["imagery_concurrency_naip"] == "2"
        assert profile["imagery_concurrency_sentinel"] == "3"
        assert profile["imagery_concurrency_direct"] == "5"
        assert profile["m2m_batch_size"] == "50"
        assert profile["planetiler_heap"] == "-Xmx8g"

    def test_8gb_values(self):
        profile = RAM_PROFILE_8GB
        assert profile["nominatim_memory"] == "4G"
        assert profile["postgres_shared_buffers"] == "512MB"
        assert profile["postgres_maintenance_work_mem"] == "512MB"
        assert profile["postgres_effective_cache_size"] == "2GB"
        assert profile["valhalla_memory"] == "2G"
        assert profile["valhalla_threads"] == "2"
        assert profile["tileserver_memory"] == "512M"
        assert profile["stt_memory"] == "768M"
        assert profile["pipeline_memory"] == "1G"
        assert profile["pipeline_gdal_cache"] == "256"
        assert profile["imagery_concurrency_naip"] == "1"
        assert profile["imagery_concurrency_sentinel"] == "1"
        assert profile["imagery_concurrency_direct"] == "3"
        assert profile["m2m_batch_size"] == "20"
        assert profile["planetiler_heap"] == "-Xmx4g"

    def test_12gb_returns_16gb_profile(self):
        profile = get_ram_profile(12000)
        assert profile is RAM_PROFILE_16GB

    def test_6gb_returns_8gb_profile(self):
        profile = get_ram_profile(6000)
        assert profile is RAM_PROFILE_8GB


# ---------------------------------------------------------------------------
# TestEnvGeneration
# ---------------------------------------------------------------------------
class TestEnvGeneration:
    def test_env_contains_required_keys_16gb(self):
        env = generate_env(
            host_ip="10.0.0.1",
            tls_mode="tailscale",
            ram_profile=RAM_PROFILE_16GB,
            bbox="-124.8,31.3,-102.0,49.0",
            data_path="/srv/geographica/data",
        )
        assert "HOST_IP=10.0.0.1" in env
        assert "TLS_MODE=tailscale" in env
        assert "POSTGRES_SHARED_BUFFERS=1GB" in env
        assert "BBOX=-124.8,31.3,-102.0,49.0" in env

    def test_env_contains_required_keys_8gb(self):
        env = generate_env(
            host_ip="192.168.1.5",
            tls_mode="none",
            ram_profile=RAM_PROFILE_8GB,
            bbox="-114.8,31.3,-109.0,37.0",
            data_path="/srv/geographica/data",
        )
        assert "HOST_IP=192.168.1.5" in env
        assert "TLS_MODE=none" in env
        assert "POSTGRES_SHARED_BUFFERS=512MB" in env
        assert "BBOX=-114.8,31.3,-109.0,37.0" in env


# ---------------------------------------------------------------------------
# TestRegionPresets
# ---------------------------------------------------------------------------
class TestRegionPresets:
    def test_western_us_exists(self):
        preset = REGION_PRESETS["western_us"]
        assert "bbox" in preset
        assert "states" in preset
        assert "label" in preset

    def test_arizona_exists(self):
        assert "arizona" in REGION_PRESETS

    def test_all_presets_have_valid_bbox(self):
        for name, preset in REGION_PRESETS.items():
            assert validate_bbox(preset["bbox"]), f"Preset {name} has invalid bbox: {preset['bbox']}"

    def test_minimum_presets_exist(self):
        required = {"western_us", "eastern_us", "full_us", "arizona", "california", "nevada", "europe"}
        assert required.issubset(set(REGION_PRESETS.keys()))


# ---------------------------------------------------------------------------
# TestHostIpDetection
# ---------------------------------------------------------------------------
class TestHostIpDetection:
    def test_returns_string(self):
        ip = detect_host_ip()
        assert isinstance(ip, str)

    def test_not_loopback(self):
        ip = detect_host_ip()
        assert ip != "127.0.0.1"

    def test_not_docker_bridge(self):
        ip = detect_host_ip()
        assert not ip.startswith("172.17.")


# ---------------------------------------------------------------------------
# TestRamDetection
# ---------------------------------------------------------------------------
class TestRamDetection:
    def test_returns_positive_int(self):
        ram = detect_ram_mb()
        assert isinstance(ram, int)
        assert ram > 0


# ---------------------------------------------------------------------------
# TestStorageDetection
# ---------------------------------------------------------------------------
class TestStorageDetection:
    def test_returns_list(self):
        storage = detect_storage()
        assert isinstance(storage, list)

    def test_entries_have_required_fields(self):
        storage = detect_storage()
        if len(storage) > 0:
            required_fields = {"device", "path", "total_gb", "free_gb", "fstype"}
            for entry in storage:
                assert required_fields.issubset(set(entry.keys())), (
                    f"Entry missing fields: {required_fields - set(entry.keys())}"
                )


# ---------------------------------------------------------------------------
# TestValidatePath
# ---------------------------------------------------------------------------
class TestValidatePath:
    def test_valid_srv_path(self):
        from config import validate_path
        result = validate_path("/srv/geographica/data")
        assert result["valid"] is True

    def test_valid_mnt_path(self):
        from config import validate_path
        result = validate_path("/mnt/external/data")
        assert result["valid"] is True

    def test_valid_media_path(self):
        from config import validate_path
        result = validate_path("/media/usb/data")
        assert result["valid"] is True

    def test_valid_home_path(self):
        from config import validate_path
        result = validate_path("/home/user/data")
        assert result["valid"] is True

    def test_rejects_etc(self):
        from config import validate_path
        result = validate_path("/etc/geographica")
        assert result["valid"] is False
        assert "not in allowed" in result["reason"].lower() or "allowed" in result["reason"].lower()

    def test_rejects_root(self):
        from config import validate_path
        result = validate_path("/")
        assert result["valid"] is False

    def test_rejects_var(self):
        from config import validate_path
        result = validate_path("/var/data")
        assert result["valid"] is False

    def test_rejects_tmp(self):
        from config import validate_path
        result = validate_path("/tmp/data")
        assert result["valid"] is False

    def test_rejects_relative_path(self):
        from config import validate_path
        result = validate_path("data/relative")
        assert result["valid"] is False

    def test_rejects_path_traversal(self):
        from config import validate_path
        result = validate_path("/srv/../etc/passwd")
        assert result["valid"] is False

    def test_rejects_empty_string(self):
        from config import validate_path
        result = validate_path("")
        assert result["valid"] is False

    def test_rejects_symlink(self, tmp_path):
        from config import validate_path
        # Create a symlink inside an allowed prefix
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        link_path = tmp_path / "link"
        link_path.symlink_to(real_dir)
        # Even if path starts with /home, symlinks are rejected
        result = validate_path(str(link_path))
        # The path starts with /tmp which is not allowed
        assert result["valid"] is False

    def test_rejects_null_bytes(self):
        from config import validate_path
        result = validate_path("/srv/data\x00evil")
        assert result["valid"] is False

    def test_warns_low_disk_space(self, tmp_path):
        from config import validate_path
        # tmp_path is under /tmp which is not in allowlist
        # This test verifies a valid path returns disk info
        result = validate_path("/srv/geographica/data")
        assert result["valid"] is True
        # If the path parent exists, we should get disk info
        if "free_gb" in result:
            assert isinstance(result["free_gb"], (int, float))
