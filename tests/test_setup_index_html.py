from pathlib import Path
INDEX = Path(__file__).parent.parent / "setup" / "static" / "index.html"


def test_step1_has_data_drive_select():
    assert 'id="data-drive"' in INDEX.read_text()


def test_step1_has_data_subpath_input():
    assert 'id="data-subpath"' in INDEX.read_text()


def test_step1_has_data_custom_path_input():
    assert 'id="data-custom-path"' in INDEX.read_text()


def test_step1_has_data_path_hint_span():
    assert 'id="data-path-hint"' in INDEX.read_text()


def test_step1_removes_host_ip_field():
    assert 'id="host-ip"' not in INDEX.read_text()
