"""Session state manager — scoped subgraphs for agent session continuity.

Design:
- Each agent session gets a lightweight ``Session`` object that accumulates
  context (entities, findings, references) during an agent run.
- Sessions are in-memory (V1).  A future V2 can persist session checkpoints
  to disk for crash recovery.
- On ``end_session()`` the accumulated context is bridged into the
  permanent inbox (via ``finding-*.md`` files) so subsequent agents can
  benefit from the learnings.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class Session:
    """A lightweight agent session tracking context during a run."""

    def __init__(self, agent_id: str, project: str):
        self.id = str(uuid.uuid4())[:12]
        self.agent_id = agent_id
        self.project = project
        self.context: dict[str, str] = {}  # key -> value
        self.created_at = datetime.now(timezone.utc)
        self.active = True

    def __repr__(self) -> str:
        return (
            f"<Session {self.id} agent={self.agent_id!r}"
            f" project={self.project!r} active={self.active}>"
        )


class SessionManager:
    """Manages scoped subgraphs (sessions) per agent per project.

    Sessions cache recent interactions and can be bridged to the permanent
    inbox on close.
    """

    def __init__(self, base_dir: str = "~/.loom"):
        self.base_dir = Path(base_dir).expanduser()
        self._sessions: dict[str, Session] = {}

    async def start_session(self, agent_id: str, project: str) -> Session:
        """Create a new session scoped to this agent+project."""
        session = Session(agent_id=agent_id, project=project)
        self._sessions[session.id] = session
        logger.debug("Session started: %s", session)
        return session

    async def end_session(self, session_id: str) -> None:
        """Mark a session as inactive and bridge learnings to permanent inbox."""
        session = self._sessions.get(session_id)
        if session is None:
            logger.warning("end_session called for unknown id: %s", session_id)
            return
        if not session.active:
            return  # already closed — don't re-bridge
        session.active = False

        # Bridge notable context items to the inbox as findings
        if session.context:
            await self._bridge_to_inbox(session)

    async def add_context(
        self, session_id: str, key: str, value: str
    ) -> None:
        """Add a context item to an active session."""
        session = self._sessions.get(session_id)
        if session is None or not session.active:
            logger.warning("add_context for inactive/unknown session: %s", session_id)
            return
        session.context[key] = value

    async def get_session(self, session_id: str) -> Session | None:
        """Return a session by id, or None."""
        return self._sessions.get(session_id)

    async def list_active_sessions(
        self, project: str | None = None
    ) -> list[Session]:
        """Return active sessions, optionally filtered by project."""
        result = [
            s
            for s in self._sessions.values()
            if s.active and (project is None or s.project == project)
        ]
        return sorted(result, key=lambda s: s.created_at)

    async def _bridge_to_inbox(self, session: Session) -> None:
        """Persist important learnings from a session to the permanent inbox."""
        inbox = self.base_dir / "inbox" / session.project
        try:
            inbox.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "Session %s: failed to create inbox directory: %s",
                session.id, exc,
            )
            return

        # Write context items worth persisting (excluding ephemeral refs)
        persisted = 0
        for key, value in session.context.items():
            # Skip session-internal bookkeeping keys
            if key.startswith("_"):
                continue
            finding_id = str(uuid.uuid4())[:8]
            finding_path = inbox / f"finding-{finding_id}.md"
            try:
                finding_path.write_text(
                    f"""---
agent: {session.agent_id}
project: {session.project}
session: {session.id}
timestamp: {datetime.now(timezone.utc).isoformat()}
confidence: medium
key: {key}
---
{value}
"""
                )
                persisted += 1
            except OSError as exc:
                logger.warning(
                    "Session %s: failed to bridge context item %r: %s",
                    session.id, key, exc,
                )

        if persisted:
            logger.info(
                "Session %s bridged %d context items to inbox",
                session.id,
                persisted,
            )
