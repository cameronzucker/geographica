"""Frontend cache-busting structural invariants.

Born 2026-04-25 from a field-test incident: app.js had no ?v= query
string at all, and navigation.js had a 5-day-stale ?v=20260420. iOS
Safari served cached old code for both. Cameron lost two field-test
drives to fixes that weren't actually loaded in his browser.

Two structural checks:

1. Every frontend/*.js file referenced via <script src=...> in
   index.html (excluding vendor/) MUST have a ?v=... query string.
   Without one, iOS Safari caches indefinitely.

2. For every cache-buster with a YYYYMMDD date prefix, the file's
   most recent git mtime must be on or before that date. Stale
   busters mean post-fix changes don't reach clients.

Pattern: structural file-grep test. Mirrors test_frontend_voice_picker.py.
Filename matches the .github/workflows/frontend-ci.yml path-filter glob
test_frontend_*.py.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "frontend" / "index.html"

# Match: <script src="path.js"></script> OR <script src="path.js?v=ver"></script>
SCRIPT_TAG_RE = re.compile(
    r'<script\s+src="(?P<path>[^"?]+\.js)(?:\?v=(?P<ver>[^"]+))?"\s*></script>'
)
DATE_PREFIX_RE = re.compile(r"^(\d{8})")


def _file_last_modified_yyyymmdd(rel_path: str) -> str | None:
    """Return YYYYMMDD of the most recent commit modifying rel_path, or None
    if git is unavailable / file is untracked."""
    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%cd",
            "--date=format:%Y%m%d",
            "--",
            rel_path,
        ],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        return None
    out = result.stdout.strip()
    return out if re.match(r"^\d{8}$", out) else None


def test_frontend_scripts_have_cache_busters() -> None:
    """Every frontend/*.js script tag (non-vendor) must have ?v=... query.

    Closes the 2026-04-25 incident where app.js had no cache-buster and
    iOS Safari served cached pre-fix code through two field tests.
    """
    src = INDEX_HTML.read_text(encoding="utf-8")
    missing = []
    for match in SCRIPT_TAG_RE.finditer(src):
        path = match.group("path")
        ver = match.group("ver")
        if path.startswith("vendor/"):
            continue
        if path.startswith("http"):
            continue
        if not ver:
            missing.append(path)
    assert not missing, (
        f"Frontend script(s) missing ?v=... cache-buster: {missing}. "
        f"Without a query string, iOS Safari caches indefinitely. Add "
        f"?v=YYYYMMDD or ?v=YYYYMMDD-slug to each <script src=...> tag. "
        f"See 2026-04-25 incident: app.js had no cache-buster, iOS served "
        f"cached pre-fix code through two field tests."
    )


def test_frontend_cache_busters_not_stale() -> None:
    """For each cache-buster with a YYYYMMDD prefix, the file's most-recent
    git mtime must be on or before that date.

    Closes the 2026-04-25 incident where navigation.js's ?v=20260420 was
    5 days stale; every nav-voice change since 2026-04-20 was potentially
    served from cache.
    """
    src = INDEX_HTML.read_text(encoding="utf-8")
    stale = []
    for match in SCRIPT_TAG_RE.finditer(src):
        path = match.group("path")
        ver = match.group("ver")
        if path.startswith("vendor/") or path.startswith("http"):
            continue
        if not ver:
            continue  # caught by the missing-cache-buster test
        date_match = DATE_PREFIX_RE.match(ver)
        if not date_match:
            # Cache-buster has no date prefix — can't audit. Skip rather
            # than fail; non-date busters (e.g., short content hashes)
            # are an acceptable alternative scheme.
            continue
        cache_date = date_match.group(1)
        rel_path = "frontend/" + path
        file_date = _file_last_modified_yyyymmdd(rel_path)
        if file_date is None:
            continue  # untracked or git unavailable
        if file_date > cache_date:
            stale.append(
                {
                    "path": path,
                    "cache_buster_version": ver,
                    "cache_buster_date": cache_date,
                    "file_last_modified": file_date,
                }
            )
    assert not stale, (
        f"Stale cache-buster(s) detected: {stale}. Each entry shows the "
        f"frontend file whose most recent git mtime is AFTER its cache-"
        f"buster's date prefix in index.html. Bump the cache-buster's "
        f"date prefix to be >= the file's most recent git mtime. "
        f"See 2026-04-25 incident: navigation.js was at ?v=20260420 "
        f"while the file had been modified through 2026-04-25 — iOS "
        f"served stale code through two field tests before the team "
        f"caught it."
    )
