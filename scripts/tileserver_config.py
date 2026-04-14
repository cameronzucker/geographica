"""Update TileServer GL config.json to register new MBTiles data sources.

TileServer GL v5.5.0 does NOT auto-discover MBTiles files. New data sources
must be added to config.json and TileServer restarted.
"""

import json
import os
from pathlib import Path


def add_mbtiles_to_config(config_path: Path, name: str, mbtiles_path: str) -> bool:
    """Add an MBTiles entry to TileServer config.json if not already present.

    Args:
        config_path: Path to tileserver/config.json
        name: Data source name (e.g., "imagery_noaa")
        mbtiles_path: Path to the MBTiles file as seen inside the TileServer container

    Returns:
        True if entry was added (config changed), False if already present.
    """
    config = json.loads(config_path.read_text())

    if name in config.get("data", {}):
        return False

    if "data" not in config:
        config["data"] = {}

    config["data"][name] = {"mbtiles": mbtiles_path}

    tmp_path = config_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(config_path))

    return True
