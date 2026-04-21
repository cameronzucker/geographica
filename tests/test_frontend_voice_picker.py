"""Structural invariants for the voice-picker feature.

Pattern mirrors tests/test_wake_lock_static.py. Filename matches
.github/workflows/frontend-ci.yml path-filter glob test_frontend_*.py
(closes R3 F3.12).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _function_body(src: str, decl_pattern: str) -> str:
    match = re.search(decl_pattern, src)
    assert match, f"declaration not found: {decl_pattern}"
    start = match.end() - 1
    depth = 0
    end = start
    for i, ch in enumerate(src[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return src[start : end + 1]


def test_voice_picker_js_exists_and_is_iife() -> None:
    src = read("frontend/voice-picker.js")
    head = src[:200]
    assert "(function () {" in head
    assert "'use strict'" in head
    assert "if (window.VoicePicker) return" in head


def test_voice_picker_js_exports_public_api() -> None:
    src = read("frontend/voice-picker.js")
    assert re.search(r"init\s*:\s*function", src)
    assert re.search(r"getUtteranceVoice\s*:", src)
    assert re.search(r"onVoiceListChanged\s*:\s*function", src)
    assert re.search(r"_inferGender\s*:", src)


def test_voice_picker_script_in_index_html() -> None:
    src = read("frontend/index.html")
    assert re.search(r'<script src="voice-picker\.js\?v=\d+">', src)
    wakelock_pos = src.index('src="wake-lock.js')
    vp_pos = src.index('src="voice-picker.js')
    nav_pos = src.index('src="navigation.js')
    assert wakelock_pos < vp_pos < nav_pos
    tag_match = re.search(r'<script[^>]*src="voice-picker\.js[^>]*>', src)
    assert tag_match
    assert " async" not in tag_match.group(0)


def test_preferences_section_markup_present() -> None:
    src = read("frontend/index.html")
    assert 'id="pref-voice"' in src
    assert 'id="pref-voice-select"' in src
    assert 'id="pref-voice-options"' in src
    assert 'id="pref-voice-allow-cloud"' in src
    assert 'id="pref-voice-hint"' in src
    assert 'id="pref-voice-stub"' in src
    assert 'id="pref-voice-detecting"' in src
    # Ensure the legacy button widgets are GONE — this refactor collapses them
    # into the single select above.
    assert 'pref-voice-btn' not in src, 'legacy gender buttons should be removed'
    assert 'pref-voice-advanced-toggle' not in src, 'legacy advanced disclosure should be removed'


def test_units_radios_exact_count() -> None:
    src = read("frontend/index.html")
    radios = re.findall(r'<input[^>]*type="radio"[^>]*name="units"[^>]*>', src)
    assert len(radios) == 2
    values = sorted(re.findall(r'name="units"[^>]*value="([^"]+)"', src))
    assert values == ["imperial", "metric"]


def test_coordfmt_radios_exact_count() -> None:
    src = read("frontend/index.html")
    radios = re.findall(r'<input[^>]*type="radio"[^>]*name="coordfmt"[^>]*>', src)
    assert len(radios) == 4
    values = set(re.findall(r'name="coordfmt"[^>]*value="([^"]+)"', src))
    assert values == {"dd", "dms", "maidenhead", "mgrs"}


def test_sr_only_class_defined_in_style_css() -> None:
    src = read("frontend/style.css")
    assert re.search(r"\.sr-only\s*\{", src)
    block_match = re.search(r"\.sr-only\s*\{([^}]+)\}", src)
    assert block_match
    block = block_match.group(1)
    assert "position: absolute" in block or "position:absolute" in block
    assert "clip:" in block or "clip :" in block


def test_app_js_dispatches_sidebar_event() -> None:
    src = read("frontend/app.js")
    body = _function_body(src, r"function\s+setSidebarOpen\s*\([^)]*\)\s*\{")
    assert "dispatchEvent" in body
    assert "geographica:sidebar" in body


def test_nav_ui_integrates_voice_picker() -> None:
    src = read("frontend/nav-ui.js")
    body = _function_body(src, r"function\s+onVoice\s*\([^)]*\)\s*\{")
    assert "VoicePicker" in body
    assert "getUtteranceVoice" in body
    assert "window.VoicePicker &&" in body
    speak_pos = body.find("speechSynthesis.speak(")
    cancel_pos = body.rfind("speechSynthesis.cancel()", 0, speak_pos)
    assert cancel_pos != -1, "speechSynthesis.cancel() must precede speak in onVoice"
    lines_between = body[cancel_pos:speak_pos].count("\n")
    assert lines_between <= 12


def test_prime_speech_not_modified() -> None:
    src = read("frontend/nav-ui.js")
    body = _function_body(src, r"function\s+primeSpeech\s*\([^)]*\)\s*\{")
    assert "volume" in body
    assert "SpeechSynthesisUtterance" in body
    assert "speak(" in body
    assert "VoicePicker" not in body
    assert "utterance.voice =" not in body
    assert "utterance.voice=" not in body


def test_no_shrek_references() -> None:
    for rel in ("frontend/voice-picker.js", "frontend/index.html", "frontend/style.css"):
        src = read(rel)
        assert "shrek" not in src.lower(), f'{rel}: "shrek" reference present'


def test_sidebar_tab_persistence_wired() -> None:
    src = read("frontend/app.js")
    # Click handler persists the selected tab
    assert re.search(r"localStorage\.setItem\s*\(\s*['\"]sidebar-last-tab['\"]", src), \
        "tab-click handler must persist last-selected tab to localStorage"
    # Restore function exists
    assert "restoreLastSidebarTab" in src, \
        "restoreLastSidebarTab helper must exist"
    # Restore is called AFTER initAdmin in DOMContentLoaded (admin-polling race fix)
    init_admin_pos = src.find("initAdmin()")
    restore_pos = src.find("restoreLastSidebarTab()")
    assert init_admin_pos != -1, "initAdmin() call not found in app.js"
    assert restore_pos != -1, "restoreLastSidebarTab() call not found in app.js"
    assert init_admin_pos < restore_pos, (
        "restoreLastSidebarTab() must be called AFTER initAdmin() — "
        "otherwise restored-to-admin loses polling (adversarial-review finding)"
    )

    # Null-guard on target panel prevents crash if future refactor drops a panel
    # while leaving the button. Load-bearing because restoreLastSidebarTab
    # exercises the click path programmatically on every page load.
    assert re.search(
        r"var\s+panelEl\s*=\s*document\.getElementById\(target\)\s*;\s*if\s*\(\s*!panelEl\s*\)\s*return",
        src,
    ), "tab-click handler must null-guard target panel before mutating DOM"
