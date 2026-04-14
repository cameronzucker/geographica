"""Security utilities for external imagery download pipelines.

Prevents path traversal, validates file magic bytes, and sanitizes
identifiers received from external servers (Copernicus, USDA).

See spec security requirements S1-S2 in
docs/superpowers/specs/2026-04-09-imagery-sources-sentinel-naip-design.md
"""

import re
from pathlib import Path


# Magic-byte signatures keyed by format name.
_MAGIC_BYTES: dict[str, list[bytes]] = {
    "geotiff": [b"II\x2a\x00", b"MM\x00\x2a"],
    "jp2": [b"\x00\x00\x00\x0cjP"],
}


def safe_staging_path(staging_dir: Path, filename: str) -> Path:
    """Return ``staging_dir / filename`` after rejecting unsafe filenames.

    Raises ``ValueError`` if *filename* contains null bytes, backslashes,
    absolute-path separators, ``..`` components, or would resolve outside
    *staging_dir*.

    Args:
        staging_dir: Trusted directory that all downloads must land inside.
        filename: Server-supplied filename (basename only, no path components).

    Returns:
        Resolved path guaranteed to be a child of *staging_dir*.

    Raises:
        ValueError: On any path-traversal attempt.
    """
    if "\x00" in filename:
        raise ValueError("path traversal: null bytes in filename")
    if "\\" in filename:
        raise ValueError("path traversal: backslash in filename")
    if filename.startswith("/"):
        raise ValueError("path traversal: absolute path in filename")
    if ".." in Path(filename).parts:
        raise ValueError("path traversal: '..' component in filename")

    result = staging_dir / filename
    if not result.resolve().is_relative_to(staging_dir.resolve()):
        raise ValueError(f"path traversal: '{filename}' escapes staging directory")

    return result


def validate_file_header(file_path: Path, expected_format: str) -> bool:
    """Return True if *file_path* starts with a known magic sequence for *expected_format*.

    Args:
        file_path: Path to the file to inspect.
        expected_format: One of ``"geotiff"`` or ``"jp2"``.

    Returns:
        ``True`` if the file header matches any known signature for the format,
        ``False`` otherwise (including empty files or unknown formats).
    """
    signatures = _MAGIC_BYTES.get(expected_format, [])
    if not signatures:
        return False

    max_len = max(len(sig) for sig in signatures)
    try:
        header = file_path.read_bytes()[:max_len]
    except OSError:
        return False

    if not header:
        return False

    return any(header[: len(sig)] == sig for sig in signatures)


def sanitize_scene_id(scene_id: str) -> str:
    """Strip non-alphanumeric/underscore characters from a scene identifier.

    Consecutive non-safe characters are collapsed to a single ``_``, and
    leading/trailing underscores are removed.

    Args:
        scene_id: Raw scene identifier (e.g. from Copernicus API).

    Returns:
        Safe string containing only ``[a-zA-Z0-9_]``.
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", scene_id).strip("_")


def sanitize_layer_name(name: str) -> str:
    """Sanitize a user-provided layer name for use as an MBTiles filename.

    Lowercases, strips non-alphanumeric characters (except underscore),
    truncates to 32 chars. Rejects path traversal attempts.

    Args:
        name: User-provided layer name.

    Returns:
        Safe string containing only ``[a-z0-9_]``, max 32 chars.

    Raises:
        ValueError: On path traversal attempts, null bytes, or empty result.
    """
    if "\x00" in name:
        raise ValueError("path traversal: null bytes in name")
    if "/" in name or "\\" in name:
        raise ValueError("path traversal: path separator in name")
    if ".." in name:
        raise ValueError("path traversal: '..' in name")

    result = re.sub(r"[^a-z0-9_]", "_", name.lower()).strip("_")
    result = re.sub(r"_+", "_", result)
    result = result[:32].rstrip("_")

    if not result:
        raise ValueError("layer name empty after sanitization")

    return result


def sanitize_fips(fips: str) -> str:
    """Validate and return a 5-digit FIPS county code.

    Args:
        fips: Expected 5-digit numeric county FIPS code.

    Returns:
        The original string if valid.

    Raises:
        ValueError: If *fips* is not exactly five decimal digits.
    """
    if not re.match(r"^\d{5}$", fips):
        raise ValueError(f"FIPS code must be exactly 5 digits, got: '{fips}'")
    return fips
