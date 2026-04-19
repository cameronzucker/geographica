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
