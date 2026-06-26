"""Multi-format document ingestion — extract text from various formats.

Design:
- ``DocumentIngestor`` accepts files (PDF, JSON, plain text, Markdown) and
  extracts their text content for downstream processing.
- Results are written as findings to the project inbox so they become
  discoverable via recall, search, and the knowledge graph.
- V1 supports: plain text (.txt), markdown (.md), JSON (.json), Python (.py).
  PDF support requires an optional ``pymupdf`` installation.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentIngestor:
    """Ingest documents and extract their text content into findings.

    Usage::

        ingestor = DocumentIngestor(loom_dir="~/.loom")
        result = await ingestor.ingest_file(
            file_path="/path/to/doc.md",
            project="my-proj",
            agent_id="ingestor",
        )
    """

    # File extensions we can handle (without extra deps)
    _text_extensions = {".txt", ".md", ".py", ".js", ".ts", ".rs", ".go",
                        ".java", ".c", ".h", ".cpp", ".hpp", ".rb",
                        ".yaml", ".yml", ".toml", ".ini", ".cfg"}

    def __init__(self, loom_dir: str = "~/.loom"):
        self.loom_dir = Path(loom_dir).expanduser()

    async def ingest_file(
        self,
        file_path: str | Path,
        project: str,
        agent_id: str = "ingestor",
    ) -> dict:
        """Ingest a single file and return the finding id.

        Returns:
            dict with ``status``, ``finding_id``, ``file_path``, and
            ``char_count``.
        """
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "error": "File not found"}

        ext = path.suffix.lower()
        content = await self._extract(path, ext)

        if content is None:
            return {"status": "error",
                    "error": f"Unsupported format: {ext}"}

        # Write to inbox as a finding
        inbox = self.loom_dir / "inbox" / project
        inbox.mkdir(parents=True, exist_ok=True)

        finding_id = str(uuid.uuid4())[:8]
        finding_path = inbox / f"finding-{finding_id}.md"
        finding_path.write_text(
            f"""---
agent: {agent_id}
project: {project}
source_file: {str(path)}
timestamp: {datetime.now(timezone.utc).isoformat()}
confidence: medium
---
FOUND: Document ingested from {path.name}
{content[:5000]}
"""
        )

        return {
            "status": "ingested",
            "finding_id": finding_id,
            "file_path": str(path),
            "char_count": len(content),
        }

    async def ingest_directory(
        self,
        dir_path: str | Path,
        project: str,
        agent_id: str = "ingestor",
    ) -> list[dict]:
        """Ingest all supported files in a directory (non-recursive)."""
        path = Path(dir_path)
        if not path.is_dir():
            return [{"status": "error", "error": "Not a directory"}]

        results = []
        for entry in sorted(path.iterdir()):
            if entry.is_file():
                result = await self.ingest_file(entry, project, agent_id)
                results.append(result)
        return results

    async def _extract(self, path: Path, ext: str) -> str | None:
        """Extract text content from a file based on its extension."""
        # Plain text
        if ext in self._text_extensions:
            return path.read_text()

        # JSON — read and pretty-print keys/structure
        if ext == ".json":
            try:
                data = json.loads(path.read_text())
                return self._describe_json(data)
            except json.JSONDecodeError:
                return path.read_text()  # fallback

        # PDF — try optional pymupdf
        if ext == ".pdf":
            return await self._extract_pdf(path)

        return None

    @staticmethod
    def _describe_json(data, prefix: str = "", depth: int = 0) -> str:
        """Describe the structure of a JSON object as text."""
        if depth > 3:
            return ""
        if isinstance(data, dict):
            lines = []
            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"{prefix}{key}:")
                    lines.append(
                        DocumentIngestor._describe_json(
                            value, prefix + "  ", depth + 1
                        )
                    )
                else:
                    lines.append(f"{prefix}{key}: {value}")
            return "\n".join(lines)
        elif isinstance(data, list):
            sample = data[:3]
            suffix = f" (+ {len(data) - 3} more)" if len(data) > 3 else ""
            return "\n".join(
                f"{prefix}[{i}]: {item}" for i, item in enumerate(sample)
            ) + suffix
        return str(data)

    @staticmethod
    async def _extract_pdf(path: Path) -> str | None:
        """Extract text from PDF using pymupdf (optional)."""
        try:
            import fitz  # pymupdf
            doc = fitz.open(str(path))
            text = "\n\n".join(
                page.get_text() for page in doc
            )
            doc.close()
            return text[:5000]
        except ImportError:
            logger.warning(
                "pymupdf not installed — PDF ingestion requires:"
                " pip install pymupdf"
            )
            return None
        except Exception as exc:
            logger.warning("PDF extraction failed for %s: %s", path, exc)
            return None
