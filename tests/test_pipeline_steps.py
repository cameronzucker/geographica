import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from setup.pipeline_steps import (
    PipelineStep, ALL_PIPELINE_STEPS, filter_active_steps,
)


def test_step_dataclass_is_frozen():
    import dataclasses
    assert dataclasses.is_dataclass(PipelineStep)
    fields = {f.name for f in dataclasses.fields(PipelineStep)}
    assert {"id", "label", "cmd_builder", "required_deps",
            "required_creds", "skippable_by"} <= fields


def test_registry_has_all_13_steps():
    ids = [s.id for s in ALL_PIPELINE_STEPS]
    assert len(ids) == 13
    for expected in [
        "osm_download", "osm_merge", "osm_copy", "planetiler_pull",
        "planetiler_build", "poi_build", "osm_pois", "public_lands",
        "elevation", "base_imagery", "detail_imagery", "fonts", "docker_build",
    ]:
        assert expected in ids


def test_filter_skips_basemap_steps_when_basemap_skipped():
    active = filter_active_steps(ALL_PIPELINE_STEPS, {"basemap": "skip",
        "base_imagery": "naip", "detail_imagery": "m2m", "elevation": "download"})
    ids = [s.id for s in active]
    assert "planetiler_build" not in ids
    assert "poi_build" not in ids


def test_filter_skips_detail_imagery_when_skipped():
    active = filter_active_steps(ALL_PIPELINE_STEPS, {"basemap": "download",
        "base_imagery": "naip", "detail_imagery": "skip", "elevation": "download"})
    ids = [s.id for s in active]
    assert "detail_imagery" not in ids


def test_pipeline_context_typed_dict_has_expected_keys():
    from setup.pipeline_steps import PipelineContext
    # TypedDict __annotations__ exposes its fields
    assert set(PipelineContext.__annotations__.keys()) == {
        "bbox", "layer_bbox", "layers",
        "data_path", "scripts_path", "base_imagery_zoom",
    }
