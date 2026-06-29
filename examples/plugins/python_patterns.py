"""Example Loom extractor plugin: detects Python design patterns."""
import re
from daemon.extractors import Extractor, ExtractedEntity

_CLASS_RE = re.compile(r"class\s+(\w+)\s*\((\w+)\)")
_DECORATOR_RE = re.compile(r"@(\w+)")

class PythonPatternExtractor(Extractor):
    async def extract(self, text: str) -> list[ExtractedEntity]:
        entities = []
        for m in _CLASS_RE.finditer(text):
            entities.append(ExtractedEntity(
                name=m.group(1), kind="class", confidence=0.75,
                context=f"inherits from {m.group(2)}",
            ))
        for m in _DECORATOR_RE.finditer(text):
            entities.append(ExtractedEntity(
                name=f"@{m.group(1)}", kind="pattern", confidence=0.6,
                context="decorator",
            ))
        return entities

def register():
    return PythonPatternExtractor()
