from pathlib import Path
JS = Path(__file__).parent.parent / "setup" / "static" / "setup.js"


def test_has_data_drive_listener():
    text = JS.read_text()
    assert "data-drive" in text and "addEventListener" in text


def test_resolves_full_data_path():
    text = JS.read_text()
    assert "data-subpath" in text
    assert "data-custom-path" in text


def test_calls_create_directory_on_next():
    assert "/api/create-directory" in JS.read_text()


def test_debounced_validate_path():
    assert "/api/validate-path" in JS.read_text()


def test_no_host_ip_in_config_object():
    assert "host_ip:" not in JS.read_text()


def test_completion_link_uses_location_hostname():
    assert "location.hostname" in JS.read_text()


def test_completion_link_http_port_8093():
    assert ":8093" in JS.read_text()


def test_completion_link_https_no_explicit_port():
    # https mode uses default :443 — no hardcoded explicit port required.
    text = JS.read_text()
    # Must branch on tls_mode when adding port
    assert "config.tls_mode" in text


def test_completion_link_no_config_host_ip():
    """Task 22 removed the dead `config.host_ip ||` fallback."""
    text = JS.read_text()
    assert "config.host_ip" not in text
