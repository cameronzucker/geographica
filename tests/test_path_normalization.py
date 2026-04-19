"""Regression tests for trailing-slash / double-slash path normalization.

2026-04-19 beta tester sequence:
  1. "Other (custom path)" on Step 1.
  2. Entered a path with a trailing `/`.
  3. Wizard accepted it. `config.data_path` kept the trailing slash.
  4. Pipeline started, eventually `osmium merge *-latest.osm.pbf` failed
     with "no such file or directory" because
     `f"{ctx['data_path']}/pbf"` had produced `/srv/foo//pbf` and
     downstream consumers choked on the `//`.

Two fix layers; both are tested here:

- **Frontend (setup.js) normalizes at input time.** The drive+subpath
  branch already did. The custom-path branch didn't — symmetry fix.
- **Backend (Pydantic validator) normalizes at request parse time.**
  Every request model that carries a path runs `_normalize_path_field`
  via `@field_validator`, so no handler sees a raw trailing-slash or
  doubled-slash value.

Additionally `validate_path` returns a `normalized` key; callers
prefer that over `body.path` for any filesystem op (mkdir, .env write,
etc.) so the canonical form is written through to disk.
"""
from pathlib import Path
import re


def test_frontend_custom_path_branch_normalizes():
    """setup.js's computeDataPath must normalize BOTH branches
    (drive+subpath and custom-path). Before the fix, custom-path
    trimmed whitespace only."""
    js = (Path(__file__).parent.parent / "setup" / "static" / "setup.js").read_text()
    # The helper function itself must exist.
    assert "function normalizePath" in js, (
        "setup.js must define a normalizePath() helper that collapses "
        "`//` and strips trailing `/`. Without it the custom-path branch "
        "propagates trailing slashes downstream."
    )
    # And the custom-path branch must call it.
    # Accept both the multi-line and single-line form.
    assert "normalizePath(custom)" in js or "normalizePath($('#data-custom-path')" in js, (
        "the custom-path branch of computeDataPath must run its input "
        "through normalizePath() — the drive+subpath branch already "
        "does by construction, but the custom-path branch previously "
        "just .trim()'d."
    )


def test_backend_normalize_path_field_helper():
    """The server-side helper must collapse //+ to / and strip trailing /
    (but preserve the lone root `/`)."""
    from setup.main import _normalize_path_field
    assert _normalize_path_field("/srv/foo/") == "/srv/foo"
    assert _normalize_path_field("/srv/foo//bar") == "/srv/foo/bar"
    assert _normalize_path_field("/srv/foo///bar///") == "/srv/foo/bar"
    assert _normalize_path_field("/srv") == "/srv"
    assert _normalize_path_field("/") == "/", "root must not be stripped to empty"
    assert _normalize_path_field("") == ""
    # Non-string input passes through (lets Pydantic's type layer report it).
    assert _normalize_path_field(None) is None  # type: ignore[arg-type]


def test_start_request_normalizes_data_path():
    """Pydantic validator on StartRequest must normalize a trailing-slash
    data_path at model construction. Without this, `ctx['data_path']` is
    set from the raw body and propagates into every `f"{...}/subdir"`
    string-concat in setup/runner.py (13 occurrences)."""
    from setup.main import StartRequest
    req = StartRequest(
        bbox="-112.5,33.3,-111.5,33.8",
        data_path="/srv/geographica/data/",
    )
    assert req.data_path == "/srv/geographica/data", (
        f"StartRequest should strip trailing `/`; got {req.data_path!r}"
    )

    req2 = StartRequest(
        bbox="-112.5,33.3,-111.5,33.8",
        data_path="/srv//geographica//data///",
    )
    assert req2.data_path == "/srv/geographica/data"


def test_config_request_normalizes_data_path():
    from setup.main import ConfigRequest
    req = ConfigRequest(
        tls_mode="http",
        bbox="-112.5,33.3,-111.5,33.8",
        data_path="/srv/geographica/data/",
    )
    assert req.data_path == "/srv/geographica/data"


def test_create_directory_request_normalizes_path():
    from setup.main import CreateDirectoryRequest
    req = CreateDirectoryRequest(path="/srv/geographica/data/")
    assert req.path == "/srv/geographica/data"


def test_path_request_normalizes_path():
    from setup.main import PathRequest
    req = PathRequest(path="/srv/foo///bar/")
    assert req.path == "/srv/foo/bar"


def test_checkpoint_reset_request_normalizes_data_path():
    from setup.main import CheckpointResetRequest
    req = CheckpointResetRequest(data_path="/srv/geographica/data/")
    assert req.data_path == "/srv/geographica/data"


def test_validate_path_returns_normalized_field_for_valid_input():
    """validate_path() must expose the canonical form so callers
    (create_directory, config writer, checkpoint reset) can prefer
    it over the raw body path."""
    from setup.config import validate_path
    result = validate_path("/srv/geographica/data/")
    assert result["valid"] is True, result
    assert result["normalized"] == "/srv/geographica/data", (
        f"validate_path must return normalized='/srv/geographica/data' "
        f"for input '/srv/geographica/data/'; got {result.get('normalized')!r}"
    )


def test_validate_path_still_rejects_nonallowlist_even_with_trailing_slash():
    """Normalization must not be a bypass — `/etc/` is still rejected
    after normalization strips the slash."""
    from setup.config import validate_path
    result = validate_path("/etc/")
    assert result["valid"] is False
    assert "allowed prefixes" in result.get("reason", ""), result


def test_validate_path_handles_doubled_internal_slashes():
    """`/srv//foo/` and `/srv/foo` must be equivalent."""
    from setup.config import validate_path
    a = validate_path("/srv/foo")
    b = validate_path("/srv//foo/")
    assert a["valid"] is True and b["valid"] is True
    assert a["normalized"] == b["normalized"] == "/srv/foo"
