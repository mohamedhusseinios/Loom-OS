"""AuditTrail — immutable record of every agent action for governance.

Design:
- Every action (register, heartbeat, finding, decision, task, dispatch) is
  recorded with timestamp, agent, project, action type, and details.
- SQLite-backed for durability (same process, same db).
- Read-only API for dashboards / compliance.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

logger = logging.getLogger(__name__)


class AuditTrail:
    """Persistent, append-only log of all agent actions.

    Usage::

        audit = AuditTrail("~/.loom/state.db")
        await audit.initialize()
        await audit.record(
            project="my-proj", agent_id="agent-1",
            action="finding:ingested", details={"file": "finding-001.md"},
        )
    """

    def __init__(self, db_path: str = "~/.loom/state.db"):
        self.db_path = Path(db_path).expanduser()
        self.db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        """Create the audit_events table if it doesn't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = await aiosqlite.connect(str(self.db_path))
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT DEFAULT '{}',
                timestamp TEXT NOT NULL
            )
        """)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_project ON audit_events(project)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_events(agent_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp)"
        )
        await self.db.commit()
        logger.info("AuditTrail initialized")

    async def close(self):
        if self.db:
            await self.db.close()

    async def record(
        self,
        project: str,
        agent_id: str,
        action: str,
        details: dict | None = None,
    ) -> str:
        """Record an audit event.  Returns the event id."""
        import uuid
        event_id = str(uuid.uuid4())[:12]
        now = datetime.now(timezone.utc).isoformat()

        await self.db.execute(
            "INSERT INTO audit_events (id, project, agent_id, action, details, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, project, agent_id, action, json.dumps(details or {}), now),
        )
        await self.db.commit()
        return event_id

    async def query(
        self,
        project: str | None = None,
        agent_id: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Return audit events, most-recent-first, optionally filtered."""
        where = []
        params: list[str] = []

        if project:
            where.append("project = ?")
            params.append(project)
        if agent_id:
            where.append("agent_id = ?")
            params.append(agent_id)
        if action:
            where.append("action = ?")
            params.append(action)

        clauses = ""
        if where:
            clauses = "WHERE " + " AND ".join(where)

        cursor = await self.db.execute(
            f"SELECT * FROM audit_events {clauses}"
            f" ORDER BY timestamp DESC LIMIT ?",
            [*params, limit],
        )
        rows = await cursor.fetchall()
        return [
            {
                "id": r["id"],
                "project": r["project"],
                "agent_id": r["agent_id"],
                "action": r["action"],
                "details": json.loads(r["details"] or "{}"),
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]

    async def summary(self, project: str, limit: int = 7) -> list[dict]:
        """Return a daily action count summary for the last *limit* days."""
        cursor = await self.db.execute(
            """SELECT date(timestamp) as day, action, count(*) as cnt
               FROM audit_events
               WHERE project = ?
               GROUP BY day, action
               ORDER BY day DESC, action
               LIMIT ?""",
            (project, limit * 10),  # rough upper bound
        )
        rows = await cursor.fetchall()
        result: dict[str, dict[str, int]] = {}
        for r in rows:
            day = r["day"]
            if day not in result:
                result[day] = {}
            result[day][r["action"]] = r["cnt"]
        return [
            {"day": day, "actions": actions}
            for day, actions in sorted(result.items(), reverse=True)[:limit]
        ]
