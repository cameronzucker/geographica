"""NOAA NAIP catalog refresh — validation + (later) Azure listing + P7 mechanics.

Consumed by:
- scripts/acquire_imagery.py (NOAA pipeline path) — reads the catalog only
- services/search/main.py (admin endpoints) — triggers refresh, serves the log
- CI nightly — regenerates config/noaa_naip_catalog.json baseline

Catalog shape — see docs/superpowers/specs/2026-04-20-noaa-naip-conus-expansion-design.md §3.3.
"""
import aiohttp
import json
import os
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from scripts.common.state_bboxes import STATE_BBOXES, SLUG_BY_USPS


class CatalogValidationError(Exception):
    """Raised when a catalog JSON fails structural validation."""


REQUIRED_TOP_KEYS = {
    "snapshot_version", "parser_version", "source_listing_url",
    "validation_status", "entries",
}

REQUIRED_ENTRY_KEYS = {
    "usps", "year", "dir", "tile_count",
    "tile_index_url", "tile_index_sha256",
}


def validate_catalog_structure(catalog: dict) -> None:
    """Raise CatalogValidationError on any malformed catalog.

    Verifies:
    - All REQUIRED_TOP_KEYS present
    - Every entry has all REQUIRED_ENTRY_KEYS
    - Every entry's tile_count > 0
    - Every entry's usps is a known USPS code (present in SLUG_BY_USPS)
    - Every slug (entry key) is present in STATE_BBOXES
    """
    missing_top = REQUIRED_TOP_KEYS - set(catalog)
    if missing_top:
        raise CatalogValidationError(f"missing top-level keys: {sorted(missing_top)}")

    entries = catalog["entries"]
    if not isinstance(entries, dict):
        raise CatalogValidationError("entries must be a dict")

    for slug, entry in entries.items():
        if slug not in STATE_BBOXES:
            raise CatalogValidationError(f"slug {slug!r} not in STATE_BBOXES")
        missing_entry = REQUIRED_ENTRY_KEYS - set(entry)
        if missing_entry:
            raise CatalogValidationError(
                f"entry {slug!r} missing keys: {sorted(missing_entry)}"
            )
        if entry["tile_count"] <= 0:
            raise CatalogValidationError(
                f"entry {slug!r} has tile_count={entry['tile_count']!r} (must be > 0)"
            )
        if entry["usps"] not in SLUG_BY_USPS:
            raise CatalogValidationError(
                f"entry {slug!r} has unknown usps {entry['usps']!r}"
            )


AZURE_LISTING_BASE = "https://coastalimagery.blob.core.windows.net/digitalcoast"


class AzureTruncatedError(Exception):
    """Raised when blob listing terminates before NextMarker is empty."""


async def azure_list_blob_prefixes(
    *,
    timeout_s: float = 30.0,
    max_pages: int = 20,
) -> list[str]:
    """List top-level blob prefixes (directory names with trailing /).

    Uses delimiter-based listing so we only get directory entries, not
    individual blob files. Walks all pages via <NextMarker>. Raises
    AzureTruncatedError if pagination terminates due to network error or
    non-200 response before the final page (distinct from shrinkage,
    which is a successful walk with fewer results than before).
    """
    prefixes: list[str] = []
    marker: str | None = None
    page_num = 0

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as sess:
        while page_num < max_pages:
            page_num += 1
            params = {"restype": "container", "comp": "list", "delimiter": "/", "prefix": ""}
            if marker:
                params["marker"] = marker
            try:
                async with sess.get(AZURE_LISTING_BASE, params=params) as resp:
                    if resp.status != 200:
                        raise AzureTruncatedError(
                            f"page {page_num} returned HTTP {resp.status}"
                        )
                    body = await resp.text()
            except aiohttp.ClientError as e:
                raise AzureTruncatedError(f"page {page_num} network error: {e}") from e

            root = ET.fromstring(body)
            for bp in root.iter("BlobPrefix"):
                name = bp.findtext("Name")
                if name:
                    prefixes.append(name)

            next_marker_elem = root.find("NextMarker")
            marker = (next_marker_elem.text or "").strip() if next_marker_elem is not None else ""
            if not marker:
                return prefixes

    raise AzureTruncatedError(f"listing did not terminate in {max_pages} pages")


NOAA_DIR_PATTERN = re.compile(r"^([A-Z]{2})_NAIP_(\d{4})_\d+/$")


def parse_noaa_dir(name: str) -> tuple[str, int] | None:
    """Parse 'AZ_NAIP_2021_9596/' → ('AZ', 2021). Returns None on mismatch
    or unsupported USPS code (AK, HI map to None in SLUG_BY_USPS)."""
    m = NOAA_DIR_PATTERN.match(name)
    if not m:
        return None
    usps = m.group(1)
    if SLUG_BY_USPS.get(usps) is None:
        return None
    return (usps, int(m.group(2)))


async def validate_tile_index(url: str) -> dict | None:
    """HEAD the tile-index ZIP. Returns {size_bytes, content_md5} on
    success, None on 404/error. The SHA256 is captured when the ZIP is
    later downloaded for real; HEAD gives us presence + size only."""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as sess:
            async with sess.head(url) as resp:
                if resp.status != 200:
                    return None
                return {
                    "size_bytes": int(resp.headers.get("Content-Length", "0")),
                    "content_md5": resp.headers.get("x-ms-blob-content-md5", ""),
                }
    except aiohttp.ClientError:
        return None


async def fetch_tile_count(url: str, cache_dir: Path) -> int:
    """Download the tile-index ZIP to cache_dir, unpack, and count features
    via ogr2ogr -ro -so. Returns the feature count. Raises on failure."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "tileindex.zip"
    async with aiohttp.ClientSession() as sess:
        async with sess.get(url) as resp:
            resp.raise_for_status()
            zip_path.write_bytes(await resp.read())
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(cache_dir)
    shps = list(cache_dir.glob("*.shp"))
    if not shps:
        raise RuntimeError(f"no .shp file in {cache_dir} after extracting {url}")
    result = subprocess.run(
        ["ogr2ogr", "-ro", "-so", "-f", "CSV", "/dev/stdout", str(shps[0])],
        capture_output=True, text=True, timeout=60,
    )
    for line in (result.stdout + result.stderr).splitlines():
        if "Feature Count:" in line:
            return int(line.split(":")[1].strip())
    raise RuntimeError(f"Could not determine feature count for {shps[0]}")


def write_snapshot(snapshots_dir: Path, catalog: dict, *, ts: str) -> Path:
    """Write snapshot atomically: tmp + fsync + rename.

    Returns the final snapshot path.
    """
    final_path = snapshots_dir / f"{ts}.json"
    tmp_path = final_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp_path, final_path)
    return final_path


def swap_symlink(link_path: Path, target_path: Path) -> None:
    """Atomic symlink replacement via tmp-symlink + rename.

    After this call (modulo power-fail during os.rename):
    - link_path is a symlink pointing at target_path, OR
    - link_path does not exist (never dangling or pointing elsewhere)
    """
    tmp_link = link_path.with_suffix(link_path.suffix + ".tmp")
    if tmp_link.is_symlink() or tmp_link.exists():
        tmp_link.unlink()
    os.symlink(target_path, tmp_link)
    os.rename(tmp_link, link_path)


import fcntl
import errno
from datetime import datetime, timezone


class LockContendedError(Exception):
    def __init__(self, holder_pid: int, age_s: float):
        self.holder_pid = holder_pid
        self.age_s = age_s
        super().__init__(f"lock held by pid {holder_pid}, age {age_s:.0f}s")


class RefreshLock:
    """flock-based lockfile context manager.

    Acquires fcntl.flock(LOCK_EX | LOCK_NB). On contention, reads the
    existing lockfile to surface holder PID + age, then raises
    LockContendedError. On acquisition, writes {pid, acquired_ts} JSON
    to the sentinel file. On exit, releases the flock and unlinks
    the sentinel.
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.fd: int | None = None
        self.held = False

    def __enter__(self):
        self.fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o644)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                os.close(self.fd)
                self.fd = None
                try:
                    data = json.loads(self.path.read_text())
                    age_s = (
                        datetime.now(timezone.utc)
                        - datetime.fromisoformat(data["acquired_ts"].replace("Z", "+00:00"))
                    ).total_seconds()
                    raise LockContendedError(data["pid"], age_s) from None
                except (OSError, KeyError, ValueError):
                    raise LockContendedError(-1, 0.0) from None
            raise
        os.ftruncate(self.fd, 0)
        os.write(
            self.fd,
            json.dumps({
                "pid": os.getpid(),
                "acquired_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }).encode(),
        )
        self.held = True
        return self

    def __exit__(self, *exc):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass


def force_unlock(lock_path: Path) -> dict:
    """Remove a lockfile only if the holder PID is no longer alive.

    Returns {status: ok | lock_holder_alive | no_lock, previous_holder_pid?}.
    """
    lock_path = Path(lock_path)
    if not lock_path.exists():
        return {"status": "no_lock"}
    try:
        data = json.loads(lock_path.read_text())
        pid = data.get("pid", -1)
    except (json.JSONDecodeError, OSError):
        lock_path.unlink()
        return {"status": "ok", "previous_holder_pid": None}
    try:
        os.kill(pid, 0)
        return {"status": "lock_holder_alive", "previous_holder_pid": pid}
    except ProcessLookupError:
        lock_path.unlink()
        return {"status": "ok", "previous_holder_pid": pid}


def find_running_pipelines(data_dir: Path) -> list[Path]:
    """Scan data_dir recursively for .pipeline-state.json files with
    status=running. Returns the list of state file paths.

    Malformed JSON and non-running statuses are silently skipped —
    this function's job is only to identify live pipelines, not
    validate state file format.
    """
    data_dir = Path(data_dir)
    running: list[Path] = []
    for state_file in data_dir.rglob(".pipeline-state.json"):
        try:
            data = json.loads(state_file.read_text())
            if data.get("status") == "running":
                running.append(state_file)
        except (json.JSONDecodeError, OSError):
            continue
    return running


BASELINE_FILENAME = "0000_ci_baseline.json"


def append_refresh_log(log_path: Path, entry: dict) -> None:
    """Append one JSON object per line to the refresh-log JSONL file."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True))
        f.write("\n")


def prune_snapshots(
    snapshots_dir: Path,
    keep_user: int,
    current_target: Path | None,
    pinned: set[Path],
) -> None:
    """Prune snapshots in-place.

    Preserves (never deletes):
    - The CI baseline (filename == BASELINE_FILENAME) — immortal
    - current_target if provided — the symlink's current target
    - Every path in `pinned` — snapshots pinned by active pipelines
    - The `keep_user` newest remaining user-generated snapshots by mtime

    Everything else is deleted.
    """
    snapshots_dir = Path(snapshots_dir)
    all_snapshots = list(snapshots_dir.glob("*.json"))

    protected: set[Path] = set()
    for s in all_snapshots:
        if s.name == BASELINE_FILENAME:
            protected.add(s.resolve())

    if current_target is not None:
        protected.add(Path(current_target).resolve())

    for p in pinned:
        protected.add(Path(p).resolve())

    # Candidates for possible deletion: user-generated, not already protected
    user_candidates = [
        s for s in all_snapshots
        if s.resolve() not in protected
    ]
    # Sort newest first by mtime
    user_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Keep `keep_user` newest; delete the rest
    for s in user_candidates[keep_user:]:
        s.unlink()


# ---------------------------------------------------------------------------
# Orchestrator helpers
# ---------------------------------------------------------------------------
from contextlib import nullcontext


def _truncated_log_entry(ts: str, error_msg: str) -> dict:
    return {
        "ts": ts,
        "validation_status": "truncated",
        "error": error_msg,
    }


def _load_previous_snapshot(symlink_path: Path, new_snapshot: Path, snapshots_dir: Path) -> dict:
    """Return the previously-active snapshot dict (for computing diff).

    Resolves symlink to find the prior snapshot. If symlink didn't exist
    before this refresh, returns {} so the diff shows every state as added.
    """
    if not symlink_path.is_symlink():
        return {}
    try:
        prev_path = symlink_path.resolve()
        if prev_path == new_snapshot.resolve():
            # Symlink already points at the new snapshot (shouldn't happen
            # before we swap, but defensive); return empty diff
            return {}
        return json.loads(prev_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _collect_pinned_snapshots(data_dir: Path) -> set[str]:
    """Scan .pipeline-state.json files for catalog_snapshot fields and return
    the set of absolute paths they pin."""
    pinned: set[str] = set()
    for state_file in Path(data_dir).rglob(".pipeline-state.json"):
        try:
            data = json.loads(state_file.read_text())
            snap = data.get("catalog_snapshot")
            if snap:
                pinned.add(snap)
        except (json.JSONDecodeError, OSError):
            continue
    return pinned


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------
async def refresh_catalog(
    *,
    data_dir: Path,
    output: Path | None = None,
    no_lock: bool = False,
    no_pipeline_check: bool = False,
) -> dict:
    """Full P7 refresh. Returns dict with keys:

    - status: "ok" | "truncated" | "invalid_parse" | "locked" | "blocked_by_pipeline"
    - snapshot_path: str (when status=ok)
    - log_entry: dict (when status in {ok, truncated, invalid_parse})
    - lock_holder_pid: int (when status=locked)
    - blocked_by_pipeline: str (when status=blocked_by_pipeline)
    """
    data_dir = Path(data_dir)
    ts_iso = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = data_dir / "noaa_catalog_refresh_log.jsonl"

    # Step 0: pipeline check
    if not no_pipeline_check:
        running = find_running_pipelines(data_dir)
        if running:
            return {"status": "blocked_by_pipeline",
                    "blocked_by_pipeline": str(running[0])}

    # Step 1: lock
    lock_path = data_dir / "noaa_catalog_refresh.lock"
    lock_ctx = RefreshLock(lock_path) if not no_lock else nullcontext()
    try:
        with lock_ctx:
            # Step 2: list blobs
            try:
                prefixes = await azure_list_blob_prefixes()
            except AzureTruncatedError as e:
                entry = _truncated_log_entry(ts_iso, str(e))
                append_refresh_log(log_path, entry)
                return {"status": "truncated", "log_entry": entry}

            # Steps 3-4: parse + validate tile indexes
            entries: dict = {}
            issues: list = []
            for prefix in prefixes:
                parsed = parse_noaa_dir(prefix)
                if parsed is None:
                    continue
                usps, year = parsed
                slug = SLUG_BY_USPS[usps]
                dir_stem = prefix.rstrip("/")
                # URL pattern discovered 2026-04-20 via live Azure listing
                # (see Task 10 follow-up). The hash suffix that appears in the
                # directory name (e.g. AZ_NAIP_2021_*9596*) is NOT part of the
                # tile-index zip filename. Verified across AZ/AL/AR/CA:
                #   AZ_NAIP_2021_9596/tileindex_AZ_NAIP_2021.zip
                #   AL_NAIP_2021_9593/tileindex_AL_NAIP_2021.zip
                #   AR_NAIP_2021_9594/tileindex_AR_NAIP_2021.zip
                #   CA_NAIP_2020_9503/tileindex_CA_NAIP_2020.zip
                tile_index_url = (
                    f"{AZURE_LISTING_BASE}/{dir_stem}/"
                    f"tileindex_{usps}_NAIP_{year}.zip"
                )
                validated = await validate_tile_index(tile_index_url)
                if validated is None:
                    issues.append({"slug": slug, "reason": "tile_index_missing"})
                    continue
                cache_dir = data_dir / "noaa_cache" / f"{slug}_{year}"
                try:
                    tile_count = await fetch_tile_count(tile_index_url, cache_dir)
                except Exception as e:
                    issues.append({"slug": slug, "reason": f"tile_count_failed:{e}"})
                    continue
                entries[slug] = {
                    "usps": usps, "year": year, "dir": dir_stem,
                    "tile_count": tile_count,
                    "tile_index_url": tile_index_url,
                    "tile_index_sha256": validated["content_md5"],
                }

            # Step 5: structural validation
            catalog = {
                "snapshot_version": ts_iso,
                "parser_version": 3,
                "source_listing_url": (
                    f"{AZURE_LISTING_BASE}?restype=container&comp=list"
                    "&delimiter=/&prefix="
                ),
                "validation_status": "ok",
                "entries": entries,
                "validation_issues": issues,
            }
            try:
                validate_catalog_structure(catalog)
            except CatalogValidationError as e:
                entry = {"ts": ts_iso, "validation_status": "invalid_parse",
                         "error": str(e), "state_count": len(entries)}
                append_refresh_log(log_path, entry)
                return {"status": "invalid_parse", "log_entry": entry}

            # CI-baseline mode: write to explicit output, no snapshot/symlink/log.
            if output is not None:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(json.dumps(catalog, indent=2, sort_keys=True))
                return {"status": "ok", "output": str(output)}

            # Steps 6-7: atomic snapshot + symlink swap
            snapshots_dir = data_dir / "noaa_catalog_snapshots"
            snapshots_dir.mkdir(parents=True, exist_ok=True)
            snap_path = write_snapshot(snapshots_dir, catalog, ts=ts_iso)
            symlink_path = data_dir / "noaa_naip_catalog.json"
            prev_catalog = _load_previous_snapshot(
                symlink_path, snap_path, snapshots_dir
            )
            swap_symlink(symlink_path, snap_path)

            # Step 8: log (with diff vs. previous)
            added = sorted(set(entries) - set(prev_catalog.get("entries", {})))
            removed = sorted(set(prev_catalog.get("entries", {})) - set(entries))
            entry = {
                "ts": ts_iso, "snapshot_path": str(snap_path),
                "parser_version": 3, "state_count": len(entries),
                "added": added, "removed": removed,
                "validation_status": "ok", "validation_issues": issues,
            }
            append_refresh_log(log_path, entry)

            # Step 9: prune (respecting pinned snapshots)
            pinned = {Path(s) for s in _collect_pinned_snapshots(data_dir)}
            prune_snapshots(snapshots_dir, keep_user=10,
                            current_target=snap_path, pinned=pinned)

            return {"status": "ok", "snapshot_path": str(snap_path),
                    "log_entry": entry}
    except LockContendedError as e:
        return {"status": "locked", "lock_holder_pid": e.holder_pid,
                "lock_age_s": e.age_s}


# ---------------------------------------------------------------------------
# CLI entry
# ---------------------------------------------------------------------------
def _main() -> None:
    import argparse
    import asyncio
    parser = argparse.ArgumentParser(
        description="Refresh the NOAA NAIP catalog via Azure blob listing."
    )
    parser.add_argument("--data-dir", type=Path,
                        default=Path("/srv/geographica/data"),
                        help="Runtime data dir (default: /srv/geographica/data)")
    parser.add_argument("--output", type=Path, default=None,
                        help="CI-baseline mode: write catalog JSON here, "
                             "skip snapshot/symlink/log")
    parser.add_argument("--no-lock", action="store_true",
                        help="Skip flock acquisition (CI mode)")
    parser.add_argument("--no-pipeline-check", action="store_true",
                        help="Skip the pipeline-running block (CI mode)")
    args = parser.parse_args()
    result = asyncio.run(refresh_catalog(
        data_dir=args.data_dir, output=args.output,
        no_lock=args.no_lock, no_pipeline_check=args.no_pipeline_check,
    ))
    print(json.dumps(result, indent=2, default=str))
    if result.get("status") not in ("ok",):
        import sys
        sys.exit(1)


if __name__ == "__main__":
    _main()
