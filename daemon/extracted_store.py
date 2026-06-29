"""Sidecar store for LLM-extracted, non-AST graph edges.

Graphify rebuilds graph.json from source AST on every build, which would erase
LLM-derived edges. We persist them separately (per project) and merge at
query/render time. JSON is sufficient for V1 (<10K edges), matching Loom's
zero-infra philosophy.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from daemon.extractors import ExtractedEntity


class ExtractedEdgeStore:
    def __init__(self, loom_dir: str | None = None):
        self.base = Path(loom_dir or os.path.expanduser("~/.loom")) / "extracted"

    def _path(self, project: str) -> Path:
        return self.base / f"{project}.json"

    async def add(self, project: str, source_file: str, entities: list[ExtractedEntity]) -> None:
        self.base.mkdir(parents=True, exist_ok=True)
        rows = await self.load(project)
        for e in entities:
            rows.append({
                "name": e.name,
                "kind": e.kind,
                "confidence": e.confidence,
                "context": e.context,
                "relationships": [list(r) for r in e.relationships],
                "source_file": source_file,
                "source": "llm",
            })
        self._path(project).write_text(json.dumps(rows, indent=2))

    async def load(self, project: str) -> list[dict]:
        p = self._path(project)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            return []