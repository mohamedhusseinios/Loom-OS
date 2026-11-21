"""Load family YAML files into a pattern registry."""

from __future__ import annotations

from pathlib import Path

import yaml

from coding_agent.patterns.schema import PatternDoc, PatternSchemaError, parse_family_doc


class PatternRegistry:
    def __init__(self, docs: list[PatternDoc]) -> None:
        by_id: dict[str, PatternDoc] = {}
        for doc in docs:
            if doc.id in by_id:
                raise PatternSchemaError(f"duplicate pattern id {doc.id!r}")
            by_id[doc.id] = doc
        self._by_id = by_id

    def get(self, id: str) -> PatternDoc:
        try:
            return self._by_id[id]
        except KeyError:
            raise KeyError(id) from None

    def active_families(self) -> list[PatternDoc]:
        return [doc for doc in self._by_id.values() if doc.status == "active"]


def load_patterns(directory: Path) -> PatternRegistry:
    docs: list[PatternDoc] = []
    for path in sorted(directory.glob("*.yaml")):
        if not path.is_file():
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise PatternSchemaError(f"{path.name}: invalid YAML: {exc}") from exc
        docs.append(parse_family_doc(raw, source=path.name))
    return PatternRegistry(docs)
