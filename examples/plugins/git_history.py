"""Example Loom extractor plugin: extracts entities from git commit messages.

NOTE: This plugin reads from the finding text, not from git directly.
It's useful when agents paste commit messages into findings.
"""
import re
from daemon.extractors import Extractor, ExtractedEntity

_COMMIT_RE = re.compile(r"(?:fix|feat|docs|refactor|test|chore)\((\w+)\):\s*(.+)", re.IGNORECASE)

class GitHistoryExtractor(Extractor):
    async def extract(self, text: str) -> list[ExtractedEntity]:
        entities = []
        for m in _COMMIT_RE.finditer(text):
            scope = m.group(1)
            msg = m.group(2).strip()[:80]
            entities.append(ExtractedEntity(
                name=scope, kind="module", confidence=0.7,
                context=f"git commit: {msg}",
            ))
        return entities

def register():
    return GitHistoryExtractor()
