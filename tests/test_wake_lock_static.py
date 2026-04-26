"""Structural invariants for the wake-lock feature.

These tests verify file presence, script load ordering, hook integrity,
and the absence of the rejected NoSleep.js design. They intentionally
parse JS with brace-tracking and comment-stripping rather than bare
grep, per spec §6.1.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def read(relpath: str) -> str:
    return (ROOT / relpath).read_text(encoding="utf-8")


def function_body(src: str, func_decl: str) -> str:
    """Return the body of a function declaration in JS source, tracking braces."""
    idx = src.find(func_decl)
    if idx < 0:
        raise ValueError(f"function declaration not found: {func_decl!r}")
    start = src.index("{", idx) + 1
    depth = 1
    i = start
    while depth > 0 and i < len(src):
        c = src[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


def strip_js_noise(src: str) -> str:
    """Remove JS // and /* */ comments and string literals so grep-style checks
    don't fire on commented-out calls or string contents.
    """
    src = re.sub(r"//.*?$", "", src, flags=re.MULTILINE)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r'"(?:\\.|[^"\\])*"', '""', src)
    src = re.sub(r"'(?:\\.|[^'\\])*'", "''", src)
    src = re.sub(r"`(?:\\.|[^`\\])*`", "``", src)
    return src


def strip_js_comments_only(src: str) -> str:
    """Remove JS // and /* */ comments but preserve string literals.

    Use this when the tokens you're asserting appear *inside* string literals
    (e.g. setAttribute('aria-hidden', ...) or classList.add('nav-active')).
    Comment-stripping is still done so that commented-out code can't false-pass.
    """
    src = re.sub(r"//.*?$", "", src, flags=re.MULTILINE)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return src


# ---------- Test 1 + 2: silent.mp4 vendored correctly ----------

def test_silent_mp4_exists_and_is_small():
    p = ROOT / "frontend/vendor/silent.mp4"
    assert p.is_file(), "frontend/vendor/silent.mp4 must exist"
    size = p.stat().st_size
    assert size < 2048, f"silent.mp4 must be < 2048 bytes; got {size}"


def test_silent_mp4_has_no_audio_stream():
    """Uses ffprobe if available; skips with clear reason if not."""
    p = ROOT / "frontend/vendor/silent.mp4"
    try:
        out = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a",
                "-show_entries",
                "stream=codec_type",
                str(p),
            ],
            stderr=subprocess.STDOUT,
        )
    except FileNotFoundError:
        pytest.skip("ffprobe not installed; cannot verify audio-track absence")
    assert out.strip() == b"", (
        f"silent.mp4 must have no audio stream; ffprobe output: {out!r}"
    )


# ---------- Test 3: silent-video-lock.js exports correct API ----------

def test_silent_video_lock_js_exists_and_exports_api():
    src = read("frontend/silent-video-lock.js")
    clean = strip_js_noise(src)
    # IIFE guard
    assert "if (window.SilentVideoLock) return" in clean, "duplicate-load guard missing"
    # Export assignment
    export_match = re.search(
        r"window\.SilentVideoLock\s*=\s*\{([^}]*)\}", clean
    )
    assert export_match, "window.SilentVideoLock export not found"
    keys = export_match.group(1)
    for k in ("enable", "disable", "isActive"):
        assert k in keys, f"SilentVideoLock export missing '{k}' key"


# ---------- Test 4: wake-lock.js exports correct API + uses generation counter ----------

def test_wake_lock_js_exists_and_exports_api():
    src = read("frontend/wake-lock.js")
    clean = strip_js_noise(src)
    # Typed duplicate-load guard (post-6bc0ba3): must check that
    # window.WakeLock has an `.acquire` method, not just truthiness. The
    # simple `if (window.WakeLock) return` form short-circuits on browsers
    # that expose the native Screen Wake Lock API — `window.WakeLock` is
    # also the spec's sentinel-class name there, but the native class has
    # no `.acquire` method, so OUR IIFE never runs and the first
    # `WakeLock.acquire()` call from the navigation start path throws
    # TypeError. Guarding on `typeof ....acquire` distinguishes our module
    # from the native API. Regression here re-introduces the `6bc0ba3` bug.
    assert re.search(
        r"if\s*\(\s*window\.WakeLock\s*&&\s*typeof\s+window\.WakeLock\.acquire\b",
        clean,
    ), "typed duplicate-load guard missing — must check .acquire is callable, not just truthy (see 6bc0ba3)"
    export_match = re.search(r"window\.WakeLock\s*=\s*\{([^}]*)\}", clean)
    assert export_match, "window.WakeLock export not found"
    keys = export_match.group(1)
    for k in ("acquire", "release", "status"):
        assert k in keys, f"WakeLock export missing '{k}' key"


def test_wake_lock_uses_generation_counter():
    """Regression guard — if someone deletes the generation counter, lock-orphan bugs return."""
    src = strip_js_noise(read("frontend/wake-lock.js"))
    assert "acquireGeneration" in src, "acquireGeneration counter missing from wake-lock.js"
    # Inside acquire() body
    acquire_body = function_body(src, "function acquire()")
    assert "myGen" in acquire_body, "acquire() must capture myGen locally"
    assert "acquireGeneration" in acquire_body, (
        "acquire() must reference the module-level acquireGeneration counter"
    )


# ---------- Test 5 + 6: index.html loads scripts in correct order with cache-busters ----------

def test_index_html_loads_scripts_in_correct_order():
    html = read("frontend/index.html")
    tags = re.findall(r'<script\s+src="([^"]+)"', html)
    # Extract bare filenames (strip query strings)
    filenames = [t.split("?")[0] for t in tags]
    try:
        svl = filenames.index("silent-video-lock.js")
        wl = filenames.index("wake-lock.js")
        nav = filenames.index("nav-ui.js")
    except ValueError as e:
        pytest.fail(f"Expected script not present in index.html: {e}")
    assert svl < wl < nav, (
        "Script order must be silent-video-lock.js, then wake-lock.js, then nav-ui.js"
    )


def test_index_html_scripts_have_cache_buster():
    html = read("frontend/index.html")
    targets = [
        "silent-video-lock.js",
        "wake-lock.js",
        "navigation.js",
        "nav-ui.js",
    ]
    # Accept both ?v=YYYYMMDD and ?v=YYYYMMDD-slug forms. The slug form was
    # standardized in docs/pitfalls/implementation-pitfalls.md §16 (added
    # 2026-04-25) for differentiation when multiple bumps land in one day.
    # tests/test_frontend_cache_busting.py is the broader canonical check;
    # this test retains its narrower per-file pin for the wake-lock-relevant
    # scripts but accepts the slug suffix.
    for t in targets:
        pattern = rf'<script\s+src="{re.escape(t)}\?v=\d+(?:-[A-Za-z0-9-]+)?"'
        assert re.search(pattern, html), (
            f"{t} script tag must have a ?v=YYYYMMDD or ?v=YYYYMMDD-slug "
            f"cache-buster query"
        )


# ---------- Test 7 + 8: nav-ui.js hooks are in the right place ----------

def test_nav_ui_acquires_wake_lock_in_start_navigation():
    # Use comments-only stripping: the classList.add('nav-active') call we're
    # asserting has its argument inside a string literal, which strip_js_noise
    # would wipe. Comment-stripping still guards against commented-out calls.
    src = strip_js_comments_only(read("frontend/nav-ui.js"))
    start_body = function_body(src, "function startNavigation()")
    assert start_body.count("WakeLock.acquire()") == 1, (
        "WakeLock.acquire() must appear exactly once in startNavigation()"
    )
    # Find the line with classList.add and the line with WakeLock.acquire()
    lines = start_body.splitlines()
    class_add_idx = None
    acquire_idx = None
    prime_speech_idx = None
    for i, line in enumerate(lines):
        if "classList.add('nav-active')" in line or 'classList.add("nav-active")' in line:
            class_add_idx = i
        if "WakeLock.acquire()" in line:
            acquire_idx = i
        if "primeSpeech()" in line:
            prime_speech_idx = i
    assert class_add_idx is not None, "classList.add('nav-active') not found in startNavigation"
    assert acquire_idx is not None and acquire_idx > class_add_idx, (
        "WakeLock.acquire() must come AFTER classList.add('nav-active')"
    )
    # Assert nothing between class_add and acquire contains await / setTimeout / fetch / .then
    between_add_and_acquire = "\n".join(lines[class_add_idx + 1 : acquire_idx])
    for forbidden in ("await ", "setTimeout(", "fetch(", ".then("):
        assert forbidden not in between_add_and_acquire, (
            f"Forbidden token {forbidden!r} between classList.add and WakeLock.acquire() "
            f"(breaks user-gesture context)"
        )
    # Per spec §4.4 Do-NOT-8: also no await / setTimeout / fetch / .then between
    # classList.add and primeSpeech — the whole stretch is gesture-sensitive.
    if prime_speech_idx is not None and prime_speech_idx > class_add_idx:
        between_add_and_prime = "\n".join(lines[class_add_idx + 1 : prime_speech_idx])
        for forbidden in ("await ", "setTimeout(", "fetch(", ".then("):
            assert forbidden not in between_add_and_prime, (
                f"Forbidden token {forbidden!r} between classList.add and primeSpeech() "
                f"(breaks user-gesture context for SpeechSynthesis priming)"
            )


def test_nav_ui_releases_wake_lock_in_stop_navigation():
    src = strip_js_noise(read("frontend/nav-ui.js"))
    stop_body = function_body(src, "function stopNavigation()")
    assert stop_body.count("WakeLock.release()") == 1, (
        "WakeLock.release() must appear exactly once in stopNavigation()"
    )


# ---------- Test 9: NoSleep must be absent ----------

def test_no_nosleep_references_remain():
    for p in (ROOT / "frontend").rglob("*"):
        if not p.is_file():
            continue
        if p.suffix in {".mp4", ".png", ".ico", ".jpg"}:
            continue
        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert "NoSleep" not in content and "nosleep" not in content, (
            f"NoSleep reference remains in {p} — spec §7 forbids it"
        )


# ---------- Test 10: no CDN URLs for wake-lock assets ----------

def test_no_cdn_urls_for_wake_lock_assets():
    cdns = ("unpkg.com", "cdn.jsdelivr.net", "cdnjs.cloudflare.com")
    for rel in (
        "frontend/wake-lock.js",
        "frontend/silent-video-lock.js",
        "frontend/index.html",
    ):
        content = read(rel)
        for cdn in cdns:
            assert cdn not in content, f"{rel} references a CDN ({cdn}); must be offline-first"


# ---------- Test 11: vendor README lists silent.mp4 ----------

def test_vendor_readme_lists_silent_mp4():
    readme = read("frontend/vendor/README.md")
    assert "silent.mp4" in readme, (
        "frontend/vendor/README.md must list silent.mp4 in the vendored-libraries table"
    )


# ---------- Test 12: silent-video-lock.js sets a11y attributes ----------

def test_silent_video_lock_sets_accessibility_attributes():
    # Use comments-only stripping: tokens like 'aria-hidden' and 'tabindex'
    # appear as string literal arguments to setAttribute(). strip_js_noise
    # would wipe them. Comment-stripping still guards against commented-out refs.
    src = strip_js_comments_only(read("frontend/silent-video-lock.js"))
    for token in (
        "aria-hidden",
        "tabindex",
        "disablePictureInPicture",
        "disableRemotePlayback",
        "muted",
        "playsInline",
        "loop",
    ):
        assert token in src, (
            f"silent-video-lock.js must reference {token} per a11y/media contract"
        )
