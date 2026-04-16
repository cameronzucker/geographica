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


def remove_mbtiles_from_config(config_path: Path, name: str) -> bool:
    """Remove an MBTiles entry from TileServer config.json.

    Args:
        config_path: Path to tileserver/config.json
        name: Data source name to remove (e.g., "imagery_noaa")

    Returns:
        True if entry was removed (config changed), False if not present.
    """
    config = json.loads(config_path.read_text())

    if name not in config.get("data", {}):
        return False

    del config["data"][name]

    tmp_path = config_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(str(tmp_path), str(config_path))

    return True


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Manage TileServer GL config sources")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add an MBTiles data source")
    add_parser.add_argument("config_path", help="Path to tileserver config.json")
    add_parser.add_argument("name", help="Data source name (e.g. imagery_noaa)")
    add_parser.add_argument("mbtiles_path", help="Path to MBTiles file inside container")

    remove_parser = subparsers.add_parser("remove", help="Remove an MBTiles data source")
    remove_parser.add_argument("config_path", help="Path to tileserver config.json")
    remove_parser.add_argument("name", help="Data source name to remove")

    args = parser.parse_args()

    if args.command == "add":
        added = add_mbtiles_to_config(Path(args.config_path), args.name, args.mbtiles_path)
        if added:
            print(f"Added source '{args.name}' to {args.config_path}")
        else:
            print(f"Source '{args.name}' already exists in {args.config_path}")
        sys.exit(0)

    elif args.command == "remove":
        removed = remove_mbtiles_from_config(Path(args.config_path), args.name)
        if removed:
            print(f"Removed source '{args.name}' from {args.config_path}")
        else:
            print(f"Source '{args.name}' not found in {args.config_path}")
        sys.exit(0)
