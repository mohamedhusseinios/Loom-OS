"""State snapshots — capture agent execution state at checkpoints for time-travel debugging.

Design:
- ``StateSnapshot`` records the agent's state (activity, context, graph changes)
  at a single point in time.
- ``SnapshotManager`` stores a ring buffer of snapshots per project and
  provides time-ordered access for replay.
- Snapshots are in-memory (V1).  Persistence to disk can be added later.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_DEFAULT_MAX_SNAPSHOTS = 200


@dataclass
class StateSnapshot:
    """A point-in-time capture of agent state."""

    id: str
    project: str
    agent_id: str
    step: int           # monotonic step counter
    activity: str        # e.g. "calling read_file", "found bug in auth.py"
    context_summary: str  # brief summary of current context
    graph_nodes_added: int = 0
    graph_edges_added: int = 0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "agent_id": self.agent_id,
            "step": self.step,
            "activity": self.activity,
            "context_summary": self.context_summary,
            "graph_nodes_added": self.graph_nodes_added,
            "graph_edges_added": self.graph_edges_added,
            "timestamp": self.timestamp,
        }


class SnapshotManager:
    """Capture and replay agent state snapshots for debugging.

    Usage::

        mgr = SnapshotManager()
        await mgr.capture(
            project="my-proj", agent_id="agent-1", step=1,
            activity="reading auth.py", context_summary="2 entities in context",
        )
        # ... later ...
        history = await mgr.replay(project="my-proj", agent_id="agent-1")
    """

    def __init__(self, max_snapshots: int = _DEFAULT_MAX_SNAPSHOTS):
        self._max = max(1, max_snapshots)
        self._snapshots: dict[str, list[StateSnapshot]] = {}

    async def capture(
        self,
        project: str,
        agent_id: str,
        step: int,
        activity: str = "",
        context_summary: str = "",
        graph_nodes_added: int = 0,
        graph_edges_added: int = 0,
    ) -> StateSnapshot:
        """Record a state snapshot."""
        snap_id = str(uuid.uuid4())[:12]
        key = f"{project}:{agent_id}"

        snapshot = StateSnapshot(
            id=snap_id,
            project=project,
            agent_id=agent_id,
            step=step,
            activity=activity,
            context_summary=context_summary,
            graph_nodes_added=graph_nodes_added,
            graph_edges_added=graph_edges_added,
        )

        if key not in self._snapshots:
            self._snapshots[key] = []

        self._snapshots[key].append(snapshot)

        # Cap per-project snapshots
        while len(self._snapshots[key]) > self._max:
            self._snapshots[key].pop(0)

        return snapshot

    async def replay(
        self,
        project: str,
        agent_id: str | None = None,
        limit: int = 50,
    ) -> list[StateSnapshot]:
        """Return snapshots in chronological order, optionally filtered by agent."""
        results: list[StateSnapshot] = []

        if agent_id:
            key = f"{project}:{agent_id}"
            results = self._snapshots.get(key, [])[-limit:]
        else:
            # Return all snapshots for the project (across agents)
            for key, snaps in self._snapshots.items():
                if key.startswith(f"{project}:"):
                    results.extend(snaps[-limit:])

        results.sort(key=lambda s: s.timestamp)
        return results[-limit:]
