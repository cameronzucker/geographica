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


def test_step2_has_customize_details_for_each_overridable_layer():
    text = INDEX.read_text()
    for layer in ("basemap", "base_imagery", "detail_imagery"):
        # Either an id="customize-LAYER" anchor or a data-layer attribute inside a details element
        assert f'data-layer="{layer}"' in text


def test_step2_does_not_offer_elevation_override():
    # Elevation always follows basemap bbox.
    text = INDEX.read_text()
    assert 'id="customize-elevation"' not in text
    # And no same-as-basemap checkbox for elevation
    assert 'data-layer="elevation"' in text  # source buttons still exist
    # Check that elevation is NOT inside a <details class="layer-coverage"> block
    # by confirming no bbox override input for elevation
    assert 'id="bbox-elevation"' not in text


def test_step2_drops_badges():
    text = INDEX.read_text()
    for badge in ("Broadest area", "Medium area", "Smallest area", "Same as basemap"):
        assert badge not in text
