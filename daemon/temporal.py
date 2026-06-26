"""Temporal fact tracking — facts with validity time ranges.

Design:
- ``TemporalFact`` represents a claim that is true for a time range
  (``valid_from`` → ``valid_to`` or open-ended).
- ``TemporalTracker`` stores facts and supports queries like
  "what was true at time T?" — essential for understanding how a codebase
  or system has evolved over time.
- All state is in-memory (V1).  SQLite persistence can be added later.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class TemporalFact:
    """A fact with temporal validity bounds."""

    id: str
    project: str
    agent_id: str
    fact_text: str
    valid_from: str                # ISO timestamp
    valid_to: str | None = None    # None = still true
    active: bool = True
    expire_reason: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "project": self.project,
            "agent_id": self.agent_id,
            "fact_text": self.fact_text,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "active": self.active,
            "expire_reason": self.expire_reason,
            "created_at": self.created_at,
        }


class TemporalTracker:
    """Tracks facts with validity time ranges.

    Usage::

        tracker = TemporalTracker()
        fact = await tracker.record("auth uses bcrypt", "my-proj", "agent-1")
        # ... later, when it changes ...
        await tracker.expire(fact.id, reason="migrated to argon2")
    """

    def __init__(self):
        self._facts: dict[str, TemporalFact] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def record(
        self,
        fact_text: str,
        project: str,
        agent_id: str,
        valid_from: str | None = None,
    ) -> TemporalFact:
        """Record a new fact that is true from *valid_from* (default: now)."""
        fact_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()

        fact = TemporalFact(
            id=fact_id,
            project=project,
            agent_id=agent_id,
            fact_text=fact_text.strip(),
            valid_from=valid_from or now,
            created_at=now,
        )
        self._facts[fact_id] = fact
        return fact

    async def expire(self, fact_id: str, reason: str = "") -> TemporalFact | None:
        """Mark a fact as no longer true."""
        fact = self._facts.get(fact_id)
        if fact is None:
            return None
        fact.active = False
        fact.valid_to = datetime.now(timezone.utc).isoformat()
        fact.expire_reason = reason
        return fact

    async def get_fact(self, fact_id: str) -> TemporalFact | None:
        """Look up a single fact by id."""
        return self._facts.get(fact_id)

    async def active_facts(
        self, project: str, limit: int = 50
    ) -> list[TemporalFact]:
        """Return facts that are currently active for a project."""
        results = sorted(
            [f for f in self._facts.values()
             if f.project == project and f.active],
            key=lambda f: f.valid_from,
            reverse=True,
        )
        return results[:limit]

    async def list_facts(
        self, project: str, limit: int = 50
    ) -> list[TemporalFact]:
        """Return all facts for a project (active + expired), most-recent-first."""
        results = sorted(
            [f for f in self._facts.values() if f.project == project],
            key=lambda f: f.created_at,
            reverse=True,
        )
        return results[:limit]

    async def timeline(
        self, project: str, limit: int = 50
    ) -> list[TemporalFact]:
        """Return facts in chronological order (oldest → newest)."""
        results = sorted(
            [f for f in self._facts.values() if f.project == project],
            key=lambda f: f.valid_from,
        )
        return results[:limit]

    async def facts_at(
        self, project: str, at_time: str
    ) -> list[TemporalFact]:
        """Return facts that were active at a specific point in time."""
        results = []
        for f in self._facts.values():
            if f.project != project:
                continue
            if f.valid_from > at_time:
                continue
            if f.valid_to is not None and f.valid_to < at_time:
                continue
            results.append(f)
        return results
