"""Example Loom extractor plugin: scans for TODO/FIXME/HACK comments."""
import re
from daemon.extractors import Extractor, ExtractedEntity

_TODO_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|BUG)\b", re.IGNORECASE)

class TodoScanner(Extractor):
    async def extract(self, text: str) -> list[ExtractedEntity]:
        entities = []
        seen = set()
        for m in _TODO_RE.finditer(text):
            tag = m.group(1).upper()
            if tag not in seen:
                seen.add(tag)
                entities.append(ExtractedEntity(
                    name=tag, kind="pattern", confidence=0.8,
                    context="code annotation",
                ))
        return entities

def register():
    return TodoScanner()
