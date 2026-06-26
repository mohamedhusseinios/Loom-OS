"""Project knowledge source discovery and ingestion.

After an agent registers with a project, Loom OS scans for existing
knowledge sources — code-review-graph databases, agent context files
(CLAUDE.md, AGENTS.md, GEMINI.md), documentation, and more — and
ingests them into the shared knowledge fabric so all agents benefit.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Knowledge source definitions ──────────────────────────────────────

@dataclass
class KnowledgeSource:
    """A knowledge source definition — what to look for and who uses it."""

    source_type: str         # stable identifier: "code-review-graph", "claude-md", ...
    display_name: str        # human-readable: "Code Review Graph", "CLAUDE.md"
    description: str         # one-liner explaining the source
    used_by: list[str]       # agent canonical names that use/produce this source
    detection: str           # "file" or "dir"
    path_pattern: str        # relative path or glob pattern


KNOWN_SOURCES: list[KnowledgeSource] = [
    KnowledgeSource(
        source_type="code-review-graph",
        display_name="Code Review Graph",
        description="Dependency, community, and flow graph of the codebase",
        used_by=["codex", "claude-code", "hermes"],
        detection="dir",
        path_pattern=".code-review-graph",
    ),
    KnowledgeSource(
        source_type="graphify",
        display_name="Graphify Graph",
        description="AST-level knowledge graph (Loom OS primary)",
        used_by=["claude-code", "codex", "hermes", "gemini-cli", "copilot-cli", "aider"],
        detection="dir",
        path_pattern="graphify-out",
    ),
    KnowledgeSource(
        source_type="claude-md",
        display_name="CLAUDE.md",
        description="Project context and conventions for Claude Code",
        used_by=["claude-code"],
        detection="file",
        path_pattern="CLAUDE.md",
    ),
    KnowledgeSource(
        source_type="agents-md",
        display_name="AGENTS.md",
        description="Project context and conventions for coding agents",
        used_by=["claude-code", "codex", "gemini-cli", "aider"],
        detection="file",
        path_pattern="AGENTS.md",
    ),
    KnowledgeSource(
        source_type="cursorrules",
        display_name=".cursorrules",
        description="Cursor editor project rules and conventions",
        used_by=["cursor", "claude-code"],
        detection="file",
        path_pattern=".cursorrules",
    ),
    KnowledgeSource(
        source_type="gemini-md",
        display_name="GEMINI.md",
        description="Project context for Gemini CLI",
        used_by=["gemini-cli"],
        detection="file",
        path_pattern="GEMINI.md",
    ),
    KnowledgeSource(
        source_type="readme",
        display_name="README.md",
        description="Project overview and setup instructions",
        used_by=["claude-code", "codex", "hermes", "gemini-cli", "copilot-cli", "aider", "opencode"],
        detection="file",
        path_pattern="README.md",
    ),
    KnowledgeSource(
        source_type="docs-dir",
        display_name="docs/ directory",
        description="Project documentation directory",
        used_by=["claude-code", "codex", "hermes"],
        detection="dir",
        path_pattern="docs",
    ),
    KnowledgeSource(
        source_type="pyproject-toml",
        display_name="pyproject.toml",
        description="Python project metadata and dependencies",
        used_by=["claude-code", "codex", "hermes"],
        detection="file",
        path_pattern="pyproject.toml",
    ),
    KnowledgeSource(
        source_type="package-json",
        display_name="package.json",
        description="Node.js project metadata and dependencies",
        used_by=["claude-code", "codex", "hermes"],
        detection="file",
        path_pattern="package.json",
    ),
]


# ── Discovery ──────────────────────────────────────────────────────────

@dataclass
class DiscoveredSource:
    """A knowledge source found in a project, with its ingestion status."""

    source_type: str
    display_name: str
    description: str
    used_by: list[str]
    found: bool
    path: str | None = None       # absolute path if found
    size_bytes: int = 0            # file size or dir total
    ingested: bool = False
    ingested_at: str | None = None


def discover_knowledge_sources(project_path: str) -> list[DiscoveredSource]:
    """Scan a project directory for all known knowledge sources.

    Returns a list of ``DiscoveredSource`` objects, one per known source,
    with ``found`` indicating whether the source exists in the project.
    """
    root = Path(project_path).expanduser().resolve()
    if not root.is_dir():
        return []

    results: list[DiscoveredSource] = []
    for ks in KNOWN_SOURCES:
        target = root / ks.path_pattern
        found = target.exists()

        discovered = DiscoveredSource(
            source_type=ks.source_type,
            display_name=ks.display_name,
            description=ks.description,
            used_by=ks.used_by,
            found=found,
            path=str(target) if found else None,
            size_bytes=_get_size(target) if found else 0,
        )
        results.append(discovered)

    return results


def _get_size(path: Path) -> int:
    """Get total size of a file or directory in bytes."""
    if path.is_file():
        return path.stat().st_size
    if path.is_dir():
        total = 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = Path(dirpath) / f
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
        return total
    return 0


# ── Ingestion ──────────────────────────────────────────────────────────

async def ingest_knowledge_source(
    project: str,
    project_path: str,
    source_type: str,
    loom_dir: str = "~/.loom",
    agent_id: str = "loom-discovery",
) -> dict:
    """Ingest a discovered knowledge source into the Loom OS inbox.

    Writes findings to ``~/.loom/inbox/<project>/`` so the watcher/recall
    engine can pick them up.

    Returns a dict with ``status``, ``source_type``, and ``chars_ingested``.
    """
    from daemon.ingest import DocumentIngestor

    ingestor = DocumentIngestor(loom_dir=loom_dir)
    root = Path(project_path).expanduser().resolve()

    # Find the matching known source
    ks = next((s for s in KNOWN_SOURCES if s.source_type == source_type), None)
    if ks is None:
        return {"status": "error", "error": f"Unknown source type: {source_type}"}

    target = root / ks.path_pattern
    if not target.exists():
        return {"status": "not_found", "source_type": source_type}

    if ks.detection == "file":
        result = await ingestor.ingest_file(target, project, agent_id)
        return {
            "status": result.get("status", "error"),
            "source_type": source_type,
            "finding_id": result.get("finding_id"),
            "chars_ingested": result.get("char_count", 0),
        }

    if ks.detection == "dir":
        results = await ingestor.ingest_directory(target, project, agent_id)
        total_chars = sum(r.get("char_count", 0) for r in results if r.get("status") == "ingested")
        return {
            "status": "ingested" if total_chars > 0 else "empty",
            "source_type": source_type,
            "files_processed": len(results),
            "chars_ingested": total_chars,
        }

    return {"status": "error", "error": f"Unknown detection type: {ks.detection}"}


async def ingest_all_sources(
    project: str,
    project_path: str,
    loom_dir: str = "~/.loom",
    agent_id: str = "loom-discovery",
) -> list[dict]:
    """Discover and ingest all found knowledge sources in a project.

    This is the main entry point — call after an agent registers or when
    the user requests a refresh.

    Returns a list of ingestion results, one per found source.
    """
    discovered = discover_knowledge_sources(project_path)
    results = []
    for ds in discovered:
        if not ds.found:
            results.append({
                "source_type": ds.source_type,
                "display_name": ds.display_name,
                "found": False,
            })
            continue

        ingest_result = await ingest_knowledge_source(
            project, project_path, ds.source_type, loom_dir, agent_id
        )
        ingest_result["display_name"] = ds.display_name
        ingest_result["used_by"] = ds.used_by
        results.append(ingest_result)

    return results
