"""Event sink implementations."""

from __future__ import annotations

import json
from pathlib import Path


class JsonlEventSink:
    def __init__(self, path: Path) -> None:
        self._path = path

    def emit(self, event: dict) -> None:
        line = json.dumps(event, ensure_ascii=False) + "\n"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line)