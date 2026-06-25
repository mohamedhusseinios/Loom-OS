"""SQLite-backed agent and project registry."""

import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from daemon.models import AgentInfo, ProjectInfo, AgentStatus


class AgentRegistry:
    def __init__(self, db_path: str = "~/.agentic-os/state.db"):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        import os
        expanded = os.path.expanduser(self.db_path)
        os.makedirs(os.path.dirname(expanded), exist_ok=True)
        self.db = await aiosqlite.connect(expanded)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                agent_name TEXT NOT NULL,
                version TEXT NOT NULL,
                project TEXT NOT NULL,
                capabilities TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'online',
                last_heartbeat TEXT,
                registered_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL,
                project_path TEXT NOT NULL,
                node_count INTEGER DEFAULT 0,
                edge_count INTEGER DEFAULT 0,
                community_count INTEGER DEFAULT 0,
                last_graph_update TEXT,
                total_findings INTEGER DEFAULT 0
            )
        """)
        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()

    # --- Agent CRUD ---

    async def upsert_agent(self, agent: AgentInfo):
        await self.db.execute(
            """INSERT OR REPLACE INTO agents
               (agent_id, agent_name, version, project, capabilities, status, last_heartbeat, registered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent.agent_id,
                agent.agent_name,
                agent.version,
                agent.project,
                json.dumps(agent.capabilities),
                agent.status.value,
                agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
                agent.registered_at.isoformat(),
            ),
        )
        await self.db.commit()

    async def get_agent(self, agent_id: str) -> Optional[AgentInfo]:
        cursor = await self.db.execute(
            "SELECT * FROM agents WHERE agent_id = ?", (agent_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_agent(row)

    async def list_agents(self, project: Optional[str] = None) -> list[AgentInfo]:
        if project:
            cursor = await self.db.execute(
                "SELECT * FROM agents WHERE project = ? ORDER BY registered_at DESC",
                (project,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM agents ORDER BY registered_at DESC"
            )
        rows = await cursor.fetchall()
        return [self._row_to_agent(r) for r in rows]

    @staticmethod
    def _row_to_agent(row) -> AgentInfo:
        return AgentInfo(
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            version=row["version"],
            project=row["project"],
            capabilities=json.loads(row["capabilities"]),
            status=AgentStatus(row["status"]),
            last_heartbeat=(
                datetime.fromisoformat(row["last_heartbeat"])
                if row["last_heartbeat"]
                else None
            ),
            registered_at=datetime.fromisoformat(row["registered_at"]),
        )

    # --- Project CRUD ---

    async def upsert_project(self, project_id: str, project_path: str):
        project_name = project_id  # use project_id as display name by default
        # ON CONFLICT preserves graph stats (node_count, edge_count, etc.)
        # on re-register; INSERT OR REPLACE would reset them to defaults.
        await self.db.execute(
            """INSERT INTO projects (project_id, project_name, project_path)
               VALUES (?, ?, ?)
               ON CONFLICT(project_id) DO UPDATE SET
                   project_name = excluded.project_name,
                   project_path = excluded.project_path""",
            (project_id, project_name, project_path),
        )
        await self.db.commit()

    async def create_project(self, project_id: str, project_name: str, project_path: str) -> ProjectInfo:
        await self.db.execute(
            "INSERT INTO projects (project_id, project_name, project_path) VALUES (?, ?, ?)",
            (project_id, project_name, project_path),
        )
        await self.db.commit()
        project = await self.get_project(project_id)
        assert project is not None
        return project

    async def delete_project(self, project_id: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM projects WHERE project_id = ?", (project_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def get_project(self, project_id: str) -> Optional[ProjectInfo]:
        cursor = await self.db.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    async def list_projects(self) -> list[ProjectInfo]:
        cursor = await self.db.execute(
            "SELECT * FROM projects ORDER BY project_id"
        )
        rows = await cursor.fetchall()
        projects = []
        for row in rows:
            project = self._row_to_project(row)
            # Count active agents
            agent_cursor = await self.db.execute(
                "SELECT COUNT(*) as cnt FROM agents WHERE project = ? AND status = ?",
                (row["project_id"], "online"),
            )
            agent_row = await agent_cursor.fetchone()
            project.active_agents = agent_row["cnt"] if agent_row else 0
            projects.append(project)
        return projects

    @staticmethod
    def _row_to_project(row) -> ProjectInfo:
        return ProjectInfo(
            project_id=row["project_id"],
            project_name=row["project_name"],
            project_path=row["project_path"],
            node_count=row["node_count"] or 0,
            edge_count=row["edge_count"] or 0,
            community_count=row["community_count"] or 0,
            last_graph_update=(
                datetime.fromisoformat(row["last_graph_update"])
                if row["last_graph_update"]
                else None
            ),
            active_agents=0,
            total_findings=row["total_findings"] or 0,
        )

    async def update_graph_stats(
        self, project_id: str, nodes: int, edges: int, communities: int
    ):
        await self.db.execute(
            """UPDATE projects
               SET node_count = ?, edge_count = ?,
                   community_count = ?, last_graph_update = ?
               WHERE project_id = ?""",
            (nodes, edges, communities, datetime.now(timezone.utc).isoformat(), project_id),
        )
        await self.db.commit()
