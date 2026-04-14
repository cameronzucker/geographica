"""System detection and configuration generation for Geographica setup wizard."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


# ---------------------------------------------------------------------------
# Path validation — ALLOWLIST only, never blocklist
# ---------------------------------------------------------------------------
ALLOWED_PATH_PREFIXES: tuple[str, ...] = ("/srv", "/mnt", "/media", "/home")


# ---------------------------------------------------------------------------
# Region presets
# ---------------------------------------------------------------------------
REGION_PRESETS: dict[str, dict] = {
    "western_us": {
        "label": "Western United States",
        "bbox": "-124.8,31.3,-102.0,49.0",
        "states": ["AZ", "CA", "CO", "ID", "MT", "NV", "NM", "OR", "UT", "WA", "WY"],
        "geofabrik": [
            "arizona", "california", "colorado", "idaho", "montana",
            "nevada", "new-mexico", "oregon", "utah", "washington", "wyoming",
        ],
    },
    "eastern_us": {
        "label": "Eastern United States",
        "bbox": "-90.0,24.5,-66.9,47.5",
        "states": [
            "AL", "CT", "DE", "FL", "GA", "IN", "KY", "ME", "MD", "MA",
            "MI", "MS", "NH", "NJ", "NY", "NC", "OH", "PA", "RI", "SC",
            "TN", "VT", "VA", "WV",
        ],
        "geofabrik": [
            "alabama", "connecticut", "delaware", "florida", "georgia-us",
            "indiana", "kentucky", "maine", "maryland", "massachusetts",
            "michigan", "mississippi", "new-hampshire", "new-jersey",
            "new-york", "north-carolina", "ohio", "pennsylvania",
            "rhode-island", "south-carolina", "tennessee", "vermont",
            "virginia", "west-virginia",
        ],
    },
    "full_us": {
        "label": "Full United States",
        "bbox": "-124.8,24.5,-66.9,49.4",
        "states": ["ALL"],
        "geofabrik": ["us"],
    },
    "arizona": {
        "label": "Arizona",
        "bbox": "-114.8,31.3,-109.0,37.0",
        "states": ["AZ"],
        "geofabrik": ["arizona"],
    },
    "california": {
        "label": "California",
        "bbox": "-124.5,32.5,-114.1,42.0",
        "states": ["CA"],
        "geofabrik": ["california"],
    },
    "nevada": {
        "label": "Nevada",
        "bbox": "-120.0,35.0,-114.0,42.0",
        "states": ["NV"],
        "geofabrik": ["nevada"],
    },
    "europe": {
        "label": "Europe",
        "bbox": "-10.5,35.0,40.0,71.0",
        "states": [],
        "geofabrik": ["europe"],
    },
}


# ---------------------------------------------------------------------------
# RAM profiles
# ---------------------------------------------------------------------------
RAM_PROFILE_16GB: dict[str, str] = {
    "nominatim_memory": "8G",
    "postgres_shared_buffers": "1GB",
    "postgres_maintenance_work_mem": "1GB",
    "postgres_effective_cache_size": "4GB",
    "valhalla_memory": "4G",
    "valhalla_threads": "4",
    "tileserver_memory": "1G",
    "stt_memory": "1536M",
    "pipeline_memory": "2G",
    "pipeline_gdal_cache": "1024",
    "imagery_concurrency_naip": "2",
    "imagery_concurrency_sentinel": "3",
    "imagery_concurrency_direct": "5",
    "m2m_batch_size": "50",
    "planetiler_heap": "-Xmx8g",
}

RAM_PROFILE_8GB: dict[str, str] = {
    "nominatim_memory": "4G",
    "postgres_shared_buffers": "512MB",
    "postgres_maintenance_work_mem": "512MB",
    "postgres_effective_cache_size": "2GB",
    "valhalla_memory": "2G",
    "valhalla_threads": "2",
    "tileserver_memory": "512M",
    "stt_memory": "768M",
    "pipeline_memory": "1G",
    "pipeline_gdal_cache": "256",
    "imagery_concurrency_naip": "1",
    "imagery_concurrency_sentinel": "1",
    "imagery_concurrency_direct": "3",
    "m2m_batch_size": "20",
    "planetiler_heap": "-Xmx4g",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_bbox(bbox_str: str) -> bool:
    """Validate a comma-separated bounding box string (west,south,east,north).

    Returns False on any parse error, wrong count, or out-of-range values.
    """
    try:
        parts = bbox_str.split(",")
        if len(parts) != 4:
            return False
        west, south, east, north = (float(p) for p in parts)
    except (ValueError, TypeError):
        return False

    if not (-180 <= west <= 180 and -180 <= east <= 180):
        return False
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        return False
    if west >= east:
        return False
    if south >= north:
        return False
    return True


# ---------------------------------------------------------------------------
# RAM profile selection
# ---------------------------------------------------------------------------
def get_ram_profile(ram_mb: int) -> dict[str, str]:
    """Return 16GB profile if ram_mb >= 12000, else 8GB."""
    if ram_mb >= 12000:
        return RAM_PROFILE_16GB
    return RAM_PROFILE_8GB


# ---------------------------------------------------------------------------
# System detection
# ---------------------------------------------------------------------------
def detect_host_ip() -> str:
    """Detect the host IP address, excluding Docker bridge and loopback.

    Runs ``ip route get 1`` and extracts the ``src`` address.
    Returns "0.0.0.0" on failure.
    """
    try:
        result = subprocess.run(
            ["ip", "route", "get", "1"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return "0.0.0.0"

        match = re.search(r"src\s+(\S+)", result.stdout)
        if not match:
            return "0.0.0.0"

        ip = match.group(1)
        if ip == "127.0.0.1" or ip.startswith("172.17."):
            return "0.0.0.0"
        return ip
    except Exception:
        return "0.0.0.0"


def detect_ram_mb() -> int:
    """Read /proc/meminfo MemTotal and return megabytes. Returns 0 on failure."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    # Format: "MemTotal:       16384000 kB"
                    parts = line.split()
                    kb = int(parts[1])
                    return kb // 1024
    except Exception:
        pass
    return 0


def detect_storage() -> list[dict]:
    """Parse /proc/mounts and return real filesystem info.

    Returns a list of dicts with keys: device, path, total_gb, free_gb, fstype,
    sorted by free_gb descending.
    """
    virtual_fstypes = {
        "sysfs", "proc", "devtmpfs", "devpts", "tmpfs", "securityfs",
        "cgroup", "cgroup2", "pstore", "efivarfs", "bpf", "tracefs",
        "debugfs", "fusectl", "configfs", "mqueue", "hugetlbfs",
        "autofs", "rpc_pipefs", "overlay", "nsfs", "fuse.lxcfs",
    }

    results = []
    seen_devices: set[str] = set()

    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device, mount_path, fstype = parts[0], parts[1], parts[2]

                if fstype in virtual_fstypes:
                    continue
                if not device.startswith("/"):
                    continue
                if device in seen_devices:
                    continue
                seen_devices.add(device)

                try:
                    usage = shutil.disk_usage(mount_path)
                    results.append({
                        "device": device,
                        "path": mount_path,
                        "total_gb": round(usage.total / (1024 ** 3), 1),
                        "free_gb": round(usage.free / (1024 ** 3), 1),
                        "fstype": fstype,
                    })
                except OSError:
                    continue
    except Exception:
        pass

    results.sort(key=lambda x: x["free_gb"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Path validation
# ---------------------------------------------------------------------------
def validate_path(path_str: str) -> dict:
    """Validate a filesystem path against the ALLOWLIST.

    Returns a dict with 'valid' (bool) and optionally 'reason' (str),
    'free_gb' (float), and 'total_gb' (float).

    Security rules:
    - Path must be absolute
    - Path must start with an allowed prefix (ALLOWLIST)
    - No null bytes
    - No path traversal (resolved path must still be under allowed prefix)
    - Reject symlinks (any component that is a symlink)
    """
    if not path_str or not isinstance(path_str, str):
        return {"valid": False, "reason": "Path is empty"}

    # Reject null bytes
    if "\x00" in path_str:
        return {"valid": False, "reason": "Path contains null bytes"}

    # Must be absolute
    if not path_str.startswith("/"):
        return {"valid": False, "reason": "Path must be absolute (start with /)"}

    # Resolve to catch traversal (.. components)
    try:
        resolved = str(Path(path_str).resolve())
    except (OSError, ValueError):
        return {"valid": False, "reason": "Invalid path"}

    # Check against allowlist AFTER resolving
    if not any(resolved.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        return {"valid": False, "reason": f"Path not in allowed prefixes: {', '.join(ALLOWED_PATH_PREFIXES)}"}

    # Also check the original path before resolution — catches /srv/../etc
    if not any(path_str.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        return {"valid": False, "reason": f"Path not in allowed prefixes: {', '.join(ALLOWED_PATH_PREFIXES)}"}

    # Reject symlinks — check each existing component
    check_path = Path(resolved)
    while str(check_path) != check_path.root:
        if check_path.exists() and check_path.is_symlink():
            return {"valid": False, "reason": "Path contains a symlink, which is not allowed"}
        check_path = check_path.parent

    # Get disk space info if the path or its parent exists
    result: dict = {"valid": True}
    try:
        # Walk up to find an existing ancestor
        check = Path(resolved)
        while not check.exists() and str(check) != check.root:
            check = check.parent
        if check.exists():
            usage = shutil.disk_usage(str(check))
            result["free_gb"] = round(usage.free / (1024 ** 3), 1)
            result["total_gb"] = round(usage.total / (1024 ** 3), 1)
            if result["free_gb"] < 20:
                result["warning"] = f"Low disk space: {result['free_gb']} GB free"
    except OSError:
        pass

    return result


# ---------------------------------------------------------------------------
# Env file generation
# ---------------------------------------------------------------------------
def generate_env(
    host_ip: str,
    tls_mode: str,
    ram_profile: dict[str, str],
    bbox: str,
    data_path: str,
) -> str:
    """Generate .env file content for docker-compose."""
    lines = [
        "# Geographica .env — auto-generated by setup wizard",
        f"HOST_IP={host_ip}",
        f"TLS_MODE={tls_mode}",
        f"BBOX={bbox}",
        f"DATA_PATH={data_path}",
        "",
        "# PostgreSQL / Nominatim",
        f"NOMINATIM_MEMORY={ram_profile['nominatim_memory']}",
        f"POSTGRES_SHARED_BUFFERS={ram_profile['postgres_shared_buffers']}",
        f"POSTGRES_MAINTENANCE_WORK_MEM={ram_profile['postgres_maintenance_work_mem']}",
        f"POSTGRES_EFFECTIVE_CACHE_SIZE={ram_profile['postgres_effective_cache_size']}",
        "",
        "# Valhalla",
        f"VALHALLA_MEMORY={ram_profile['valhalla_memory']}",
        f"VALHALLA_THREADS={ram_profile['valhalla_threads']}",
        "",
        "# Services",
        f"TILESERVER_MEMORY={ram_profile['tileserver_memory']}",
        f"STT_MEMORY={ram_profile['stt_memory']}",
        f"PIPELINE_MEMORY={ram_profile['pipeline_memory']}",
        f"PIPELINE_GDAL_CACHE={ram_profile['pipeline_gdal_cache']}",
        "",
        "# Imagery pipeline",
        f"IMAGERY_CONCURRENCY_NAIP={ram_profile['imagery_concurrency_naip']}",
        f"IMAGERY_CONCURRENCY_SENTINEL={ram_profile['imagery_concurrency_sentinel']}",
        f"IMAGERY_CONCURRENCY_DIRECT={ram_profile['imagery_concurrency_direct']}",
        f"M2M_BATCH_SIZE={ram_profile['m2m_batch_size']}",
        f"PLANETILER_HEAP={ram_profile['planetiler_heap']}",
        "",
        "# GPS",
        "GPS_DEVICE=/dev/ttyAMA0",
        "",
    ]
    return "\n".join(lines)
