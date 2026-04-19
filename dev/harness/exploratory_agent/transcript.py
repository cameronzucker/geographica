"""JSONL transcript writer.

Every tool call + result, every agent text message, every checkpoint
gets a single JSON line appended. Used for debugging + replay.
"""
from __future__ import annotations

import json


class TranscriptWriter:
    def __init__(self, path: str) -> None:
        self._fh = open(path, "w", encoding="utf-8")

    def log(self, event: dict) -> None:
        self._fh.write(json.dumps(event, default=str, ensure_ascii=False))
        self._fh.write("\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()
