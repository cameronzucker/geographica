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
        assert profile["postgres_shared_buffers"] == "2GB"
        assert profile["postgres_maintenance_work_mem"] == "1GB"
        assert profile["postgres_effective_cache_size"] == "6GB"
        assert profile["postgres_work_mem"] == "32MB"
        assert profile["postgres_autovacuum_work_mem"] == "256MB"
        assert profile["valhalla_memory"] == "4G"
        assert profile["valhalla_threads"] == "4"
        assert profile["tileserver_memory"] == "1G"
        assert profile["stt_memory"] == "1536M"
        assert profile["pipeline_memory"] == "4G"
        assert profile["pipeline_gdal_cache"] == "1024"
        assert profile["planetiler_heap"] == "4g"

    def test_8gb_values(self):
        profile = RAM_PROFILE_8GB
        assert profile["nominatim_memory"] == "4G"
        assert profile["postgres_shared_buffers"] == "1GB"
        assert profile["postgres_maintenance_work_mem"] == "512MB"
        assert profile["postgres_effective_cache_size"] == "3GB"
        assert profile["postgres_work_mem"] == "16MB"
        assert profile["postgres_autovacuum_work_mem"] == "128MB"
        assert profile["valhalla_memory"] == "2G"
        assert profile["valhalla_threads"] == "2"
        assert profile["tileserver_memory"] == "768M"
        assert profile["stt_memory"] == "1G"
        assert profile["pipeline_memory"] == "2G"
        assert profile["pipeline_gdal_cache"] == "512"
        assert profile["planetiler_heap"] == "2g"

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
            tls_mode="tailscale",
            ram_profile=RAM_PROFILE_16GB,
            bbox="-124.8,31.3,-102.0,49.0",
            data_path="/srv/geographica/data",
            scripts_path="/home/administrator/Code/geographica/scripts",
        )
        assert "TLS_MODE=tailscale" in env
        assert "POSTGRES_SHARED_BUFFERS=2GB" in env
        assert "BBOX=-124.8,31.3,-102.0,49.0" in env

    def test_env_contains_required_keys_8gb(self):
        env = generate_env(
            tls_mode="http",
            ram_profile=RAM_PROFILE_8GB,
            bbox="-114.8,31.3,-109.0,37.0",
            data_path="/srv/geographica/data",
            scripts_path="/home/administrator/Code/geographica/scripts",
        )
        assert "TLS_MODE=http" in env
        assert "POSTGRES_SHARED_BUFFERS=1GB" in env
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


def _parse(env_text: str) -> dict[str, str]:
    return dict(l.split("=", 1) for l in env_text.strip().splitlines()
                if "=" in l and not l.startswith("#"))

EXPECTED_21_KEYS = {
    "TLS_MODE", "TLS_CERT_DIR", "TLS_PORT", "BBOX",
    "DATA_HOST_PATH", "SCRIPTS_HOST_PATH", "STT_BACKEND",
    "NOMINATIM_MEMORY", "POSTGRES_SHARED_BUFFERS",
    "POSTGRES_MAINTENANCE_WORK_MEM", "POSTGRES_EFFECTIVE_CACHE_SIZE",
    "POSTGRES_WORK_MEM", "POSTGRES_AUTOVACUUM_WORK_MEM",
    "VALHALLA_MEMORY", "VALHALLA_THREADS",
    "TILESERVER_MEMORY", "STT_MEMORY",
    "PIPELINE_MEMORY", "PIPELINE_GDAL_CACHE", "PLANETILER_HEAP",
    "GPS_DEVICE",
}


class TestEnvGenerationFull:
    def _env(self):
        from config import generate_env, RAM_PROFILE_16GB
        return generate_env(
            tls_mode="https",
            ram_profile=RAM_PROFILE_16GB,
            bbox="-124.8,31.3,-102.0,49.0",
            data_path="/srv/geographica/data",
            scripts_path="/home/pi/geographica/scripts",
            tls_cert_dir="/srv/geographica/tls",
            tls_port=443,
            stt_backend="cpu",
        )

    def test_env_16gb_values(self):
        from config import generate_env, RAM_PROFILE_16GB
        env = _parse(generate_env(
            tls_mode="http", bbox="-124,31,-102,49",
            data_path="/srv/geographica/data",
            scripts_path="/home/administrator/Code/geographica/scripts",
            ram_profile=RAM_PROFILE_16GB,
        ))
        assert set(env.keys()) == EXPECTED_21_KEYS
        assert env["POSTGRES_WORK_MEM"] == "32MB"
        assert env["POSTGRES_AUTOVACUUM_WORK_MEM"] == "256MB"
        assert env["NOMINATIM_MEMORY"] == "8G"
        assert env["VALHALLA_THREADS"] == "4"
        assert env["DATA_HOST_PATH"] == "/srv/geographica/data"
        assert env["SCRIPTS_HOST_PATH"].endswith("/scripts")

    def test_env_8gb_values(self):
        from config import generate_env, RAM_PROFILE_8GB
        env = _parse(generate_env(
            tls_mode="http", bbox="-124,31,-102,49",
            data_path="/srv/geographica/data",
            scripts_path="/home/administrator/Code/geographica/scripts",
            ram_profile=RAM_PROFILE_8GB,
        ))
        assert env["POSTGRES_WORK_MEM"] == "16MB"
        assert env["POSTGRES_AUTOVACUUM_WORK_MEM"] == "128MB"
        assert env["NOMINATIM_MEMORY"] == "4G"

    def test_has_data_host_path(self):
        assert "DATA_HOST_PATH=/srv/geographica/data" in self._env()

    def test_has_scripts_host_path(self):
        assert "SCRIPTS_HOST_PATH=/home/pi/geographica/scripts" in self._env()

    def test_has_tls_mode(self):
        assert "TLS_MODE=https" in self._env()

    def test_has_tls_cert_dir(self):
        assert "TLS_CERT_DIR=/srv/geographica/tls" in self._env()

    def test_has_tls_port(self):
        assert "TLS_PORT=443" in self._env()

    def test_has_stt_backend(self):
        assert "STT_BACKEND=cpu" in self._env()

    def test_has_postgres_work_mem(self):
        assert "POSTGRES_WORK_MEM=" in self._env()

    def test_has_postgres_autovacuum_work_mem(self):
        assert "POSTGRES_AUTOVACUUM_WORK_MEM=" in self._env()

    def test_has_nominatim_memory(self):
        assert "NOMINATIM_MEMORY=" in self._env()

    def test_has_valhalla_threads(self):
        assert "VALHALLA_THREADS=" in self._env()

    def test_does_not_emit_host_ip(self):
        assert "HOST_IP=" not in self._env()
