"""Structured pipeline-step registry (D5)."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Tuple, TypedDict
from setup.runner import (
    osm_download_cmd, osm_merge_cmd, osm_copy_cmd,
    planetiler_pull_cmd, planetiler_build_cmd,
    poi_build_cmd, osm_pois_cmd, public_lands_cmd, elevation_cmd,
    base_imagery_cmd, detail_imagery_cmd,
    fonts_cmd, docker_build_cmd,
)


class PipelineContext(TypedDict):
    bbox: str                      # basemap-level bbox (fallback for layers without override)
    layer_bbox: dict[str, str]     # per-layer bbox override (key = layer name)
    layers: dict[str, str]         # per-layer source choice
    data_path: str                 # host path for data output (from Step 1)
    scripts_path: str              # host path for scripts directory (= repo_root/scripts)
    base_imagery_zoom: int         # from Step 2 slider (default 15)


def _raise(msg: str):
    """Return a callable that raises NotImplementedError when invoked.
    Used for cmd_builder placeholders that Task 25 replaces with real builders."""
    def _inner(ctx: PipelineContext):
        raise NotImplementedError(msg)
    return _inner


@dataclass(frozen=True)
class PipelineStep:
    id: str
    label: str
    cmd_builder: Callable[[PipelineContext], list[str]]
    required_deps: Tuple[str, ...]
    required_creds: Tuple[str, ...]
    skippable_by: Tuple[str, ...]  # layer keys; see filter_active_steps for exact semantics


ALL_PIPELINE_STEPS: Tuple[PipelineStep, ...] = (
    PipelineStep("osm_download", "Download OSM data", osm_download_cmd,
                 ("wget",), (), ("basemap",)),
    PipelineStep("osm_merge", "Merge OSM extracts", osm_merge_cmd,
                 ("osmium-tool",), (), ("basemap",)),
    PipelineStep("osm_copy", "Stage OSM data", osm_copy_cmd,
                 (), (), ("basemap",)),
    PipelineStep("planetiler_pull", "Pull Planetiler image", planetiler_pull_cmd,
                 ("docker",), (), ("basemap",)),
    PipelineStep("planetiler_build", "Build basemap tiles", planetiler_build_cmd,
                 ("docker",), (), ("basemap",)),
    PipelineStep("poi_build", "Build POI index", poi_build_cmd,
                 ("python3",), (), ("basemap",)),
    PipelineStep("osm_pois", "Extract OSM POIs", osm_pois_cmd,
                 ("osmium-tool", "python3"), (), ("basemap",)),
    PipelineStep("public_lands", "Process public lands", public_lands_cmd,
                 ("tippecanoe", "python3"), (), ("basemap",)),
    PipelineStep("elevation", "Download elevation data", elevation_cmd,
                 ("python3",), (), ("elevation",)),
    PipelineStep("base_imagery", "Download base imagery", base_imagery_cmd,
                 ("python3",), (), ("base_imagery",)),
    PipelineStep("detail_imagery", "Download detail imagery", detail_imagery_cmd,
                 ("python3",), ("m2m", "copernicus"), ("detail_imagery",)),
    PipelineStep("fonts", "Download map fonts", fonts_cmd,
                 (), (), ("basemap",)),
    PipelineStep("docker_build", "Build Docker images", docker_build_cmd,
                 ("docker",), (), ()),
)


def filter_active_steps(all_steps, layer_selections: dict) -> tuple:
    """Return only steps whose `skippable_by` layers are not all 'skip'."""
    out = []
    for s in all_steps:
        if not s.skippable_by:
            out.append(s)
            continue
        any_active = any(
            layer_selections.get(layer) and layer_selections.get(layer) != "skip"
            for layer in s.skippable_by
        )
        if any_active:
            out.append(s)
    return tuple(out)
