"""Shared pipeline progress module.

Provides update_progress() for writing atomic JSON state files used by all
pipeline scripts (acquire_imagery, download_elevation, build_public_lands, etc.)

Design decisions:
- Atomic writes via tmp file + os.replace() + os.fsync() — prevents corruption
  on Pi 5 power loss mid-write.
- Merge semantics — preserves metadata written by the search service before
  the pipeline starts (e.g. type, bbox, estimated_tiles).
- Generic fields (items_done/items_total/item_unit) instead of source-specific
  field names, so all pipelines share one interface.
- Status values: "running", "completed", "error", "cancelled".
  Use "completed" not "complete" to match frontend/backend consumers.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


def update_progress(
    state_path: Path,
    *,
    source: str,
    status: str,
    phase: str = None,
    items_done: int = 0,
    items_total: int = 0,
    item_unit: str = "",
    bytes_done: int = 0,
    bytes_total: int = 0,
    detail: str,
    error: str = None,
    bbox: str = None,
    zoom: str = None,
) -> None:
    """Write pipeline progress to a JSON state file atomically.

    Merges new fields into any existing state so that metadata written by the
    search service before pipeline start is preserved.

    Args:
        state_path: Path to the JSON state file to write.
        source: Pipeline source identifier (e.g. "naip", "sentinel", "m2m").
        status: One of "running", "completed", "error", "cancelled".
        phase: Current pipeline phase (e.g. "downloading", "converting"). Omitted if None.
        items_done: Count of completed items.
        items_total: Total items to process.
        item_unit: Human-readable unit label (e.g. "counties", "scenes", "tiles").
        bytes_done: Bytes transferred so far.
        bytes_total: Total bytes expected.
        detail: Human-readable description of current activity.
        error: Error message when status="error". Omitted if None.
        bbox: Bounding box string (e.g. "-112,33,-111,34"). Omitted if None.
        zoom: Zoom range string (e.g. "0-14"). Omitted if None.
    """
    state_path = Path(state_path)
    now = datetime.now(timezone.utc).isoformat()

    # Load existing state (merge semantics)
    existing: dict = {}
    if state_path.exists():
        try:
            existing = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            existing = {}

    # Preserve started_at from first call; set it now if this is the first call
    started_at = existing.get("started_at", now)

    # Build updated state: start from existing, overlay new fields
    state = {**existing}
    state.update(
        source=source,
        status=status,
        items_done=items_done,
        items_total=items_total,
        item_unit=item_unit,
        bytes_done=bytes_done,
        bytes_total=bytes_total,
        detail=detail,
        started_at=started_at,
        last_updated=now,
    )

    # Optional fields: only include when provided (keeps state file clean)
    if phase is not None:
        state["phase"] = phase
    if error is not None:
        state["error"] = error
    if bbox is not None:
        state["bbox"] = bbox
    if zoom is not None:
        state["zoom"] = zoom

    # Atomic write: write to .tmp then rename
    tmp_path = state_path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, state_path)
    except Exception:
        # Clean up tmp file if something went wrong before the rename
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
