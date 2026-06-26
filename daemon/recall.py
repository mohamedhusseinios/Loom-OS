"""RecallEngine — queries the Graphify graph for entities relevant to the current agent task.

Design:
- ``recall()`` reads graph.json from the project's graphify-out directory and
  returns entities that fuzzy-match the task hint.
- The engine is stateless per call; it reads fresh from disk so there is no
  staleness window beyond the last Graphify build.
"""

import json
import logging
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
