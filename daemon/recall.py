"""RecallEngine — queries the Graphify graph for entities relevant to the current agent task.

Design:
- ``recall()`` reads graph.json from the project's graphify-out directory and
  returns entities that fuzzy-match the task hint.
- The engine is stateless per call; it reads fresh from disk so there is no
  staleness window beyond the last Graphify build.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class RecallEngine:
    """Queries the Graphify graph for entities relevant to the current agent task.

    Uses simple substring matching against node names/labels in the project's
    graph.json. The returned context string is designed to be injected as
    pre-context before an agent turn.
    """

    def __init__(self, loom_dir: str = "~/.loom"):
        self.loom_dir = Path(loom_dir).expanduser()

    async def recall(
        self,
        agent_id: str,
        project: str,
        project_path: str = "",
        task_hint: str = "",
    ) -> str:
        """Return a pre-context string from graph entities matching the task hint.

        Args:
            agent_id: The calling agent's identifier.
            project: The project name / id.
            project_path: The absolute filesystem path to the project root.
                Graphify output is expected at ``<project_path>/graphify-out/graph.json``.
            task_hint: Free-text description of the current task used to
                filter relevant entities.

        Returns:
            A newline-separated string of matching entity summaries, or an
            empty string when no graph or no matches exist.
        """
        graph_path = Path(project_path) / "graphify-out" / "graph.json" if project_path else None
        if graph_path is None or not graph_path.exists():
            return ""

        try:
            with open(graph_path) as f:
                graph = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("RecallEngine: cannot read graph %s: %s", graph_path, exc)
            return ""

        entities: list[str] = []
        keywords = task_hint.lower().split() if task_hint else []

        for node in graph.get("nodes", []):
            name = (node.get("name") or node.get("label") or "").strip()
            kind = (node.get("kind") or "").strip()
            if not name:
                continue

            if keywords:
                name_lower = name.lower()
                if not any(kw in name_lower for kw in keywords):
                    continue

            label = f"[{kind}] {name}" if kind else name
            entities.append(label[:200])

        return "\n".join(entities[:20])

    # ------------------------------------------------------------------
    # Retain (auto-learn from agent output)
    # ------------------------------------------------------------------

    async def retain(
        self,
        agent_id: str,
        project: str,
        agent_output: str,
        inbox_dir: Path | None = None,
    ) -> int:
        """Parse agent output for structured findings and write them to the inbox.

        Looking for lines prefixed with ``FOUND:``, ``PATTERN:``, or ``DECISION:``.
        Each becomes a standalone ``finding-<id>.md`` file with YAML frontmatter.

        Args:
            agent_id: The agent that produced the output.
            project: The project name.
            agent_output: The raw text output from an agent run.
            inbox_dir: Where to write findings. Defaults to
                ``<loom_dir>/inbox/<project>``.

        Returns:
            Number of finding files written.
        """
        if inbox_dir is None:
            inbox_dir = self.loom_dir / "inbox" / project

        inbox_dir.mkdir(parents=True, exist_ok=True)

        findings = self._extract_findings(agent_output)
        written = 0
        for finding in findings:
            finding_id = str(uuid.uuid4())[:8]
            finding_path = inbox_dir / f"finding-{finding_id}.md"
            finding_path.write_text(
                f"""---
agent: {agent_id}
project: {project}
timestamp: {datetime.now(timezone.utc).isoformat()}
confidence: medium
---
{finding}
"""
            )
            written += 1

        return written

    @staticmethod
    def _extract_findings(text: str) -> list[str]:
        """Extract FOUND:/PATTERN:/DECISION: lines from agent output."""
        findings: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            for prefix in ("FOUND:", "PATTERN:", "DECISION:"):
                if stripped.startswith(prefix):
                    findings.append(stripped)
                    break
        return findings
