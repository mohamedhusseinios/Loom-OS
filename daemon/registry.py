"""SQLite-backed agent and project registry."""

import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from daemon.models import AgentInfo, ProjectInfo, AgentStatus
from daemon.models import (
    AgentTaskCreatePayload, AgentTaskRecord, AgentTaskStatus,
    AgentTaskUpdatePayload, TaskProgressRecord,
)


class ProjectExistsError(Exception):
    """Raised when creating a project whose id is already tracked."""

    def __init__(self, project_id: str):
        super().__init__(f"Project already tracked: {project_id}")
        self.project_id = project_id


class AgentRegistry:
    def __init__(self, db_path: str = "~/.loom/state.db"):
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
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                target_agent TEXT NOT NULL,
                instruction TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'pending',
                dispatched_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                title TEXT NOT NULL,
                instruction TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo',
                assignee TEXT,
                priority INTEGER DEFAULT 0,
                dependencies TEXT DEFAULT '[]',
                acceptance_criteria TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                result TEXT,
                workspace_path TEXT
            )
        """)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_tasks_project_status"
            " ON agent_tasks(project, status)"
        )
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS task_progress (
                task_id TEXT NOT NULL,
                seq     INTEGER NOT NULL,
                kind    TEXT NOT NULL,
                message TEXT NOT NULL,
                ts      TEXT NOT NULL,
                PRIMARY KEY (task_id, seq)
            )
        """)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_progress_task"
            " ON task_progress(task_id)"
        )
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

    async def delete_agent(self, agent_id: str) -> bool:
        """Remove an agent from the registry. Returns True if a row was deleted."""
        cursor = await self.db.execute(
            "DELETE FROM agents WHERE agent_id = ?", (agent_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

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
        """Create a project row. Raises ``ProjectExistsError`` on id collision."""
        try:
            await self.db.execute(
                "INSERT INTO projects (project_id, project_name, project_path) VALUES (?, ?, ?)",
                (project_id, project_name, project_path),
            )
            await self.db.commit()
        except aiosqlite.IntegrityError as e:
            # PRIMARY KEY collision — surface as a typed error so the API
            # layer can map it to 409 rather than returning a 500.
            raise ProjectExistsError(project_id) from e
        project = await self.get_project(project_id)
        if project is None:  # pragma: no cover - row just inserted
            raise RuntimeError(f"Project {project_id} missing after insert")
        return project

    async def delete_project(self, project_id: str) -> bool:
        cursor = await self.db.execute(
            "DELETE FROM projects WHERE project_id = ?", (project_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    # --- Task CRUD ---

    async def create_task(
        self, task_id: str, project: str, target_agent: str, instruction: str, priority: str
    ) -> bool:
        """Insert a task row.

        Idempotent: if a row with this ``task_id`` already exists (e.g. the
        API wrote it before the inbox watcher reprocessed the file), this is
        a no-op. Returns ``True`` when a new row was created, ``False`` when
        it already existed — callers use that to decide whether to emit an
        event and avoid duplicate broadcasts.
        """
        cursor = await self.db.execute(
            "INSERT OR IGNORE INTO tasks (task_id, project, target_agent, instruction, priority) VALUES (?, ?, ?, ?, ?)",
            (task_id, project, target_agent, instruction, priority),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def list_tasks(self, project: str) -> list[dict]:
        # rowid as a stable tiebreaker: dispatched_at is second-resolution
        # (datetime('now')), so two dispatches in the same second would
        # otherwise order non-deterministically. rowid is monotonic with
        # insertion order, so DESC gives true newest-first.
        cursor = await self.db.execute(
            "SELECT * FROM tasks WHERE project = ? ORDER BY dispatched_at DESC, rowid DESC LIMIT 50",
            (project,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def complete_task(self, task_id: str):
        await self.db.execute(
            "UPDATE tasks SET status = 'completed', completed_at = ? WHERE task_id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        await self.db.commit()

    async def fail_task(self, task_id: str, error: str | None = None):
        await self.db.execute(
            "UPDATE tasks SET status = 'failed', completed_at = ? WHERE task_id = ?",
            (datetime.now(timezone.utc).isoformat(), task_id),
        )
        await self.db.commit()


    # ----------------------------------------------------------------
    # Agent task CRUD (Kanban board — Feature 2)
    # ----------------------------------------------------------------

    async def create_agent_task(self, payload: AgentTaskCreatePayload) -> str:
        import uuid
        now = datetime.now(timezone.utc).isoformat()
        task_id = str(uuid.uuid4())[:12]

        status = AgentTaskStatus.READY if (
            payload.dependencies and self._all_agent_task_deps_done(payload.dependencies)
        ) else AgentTaskStatus.TODO

        await self.db.execute(
            """INSERT INTO agent_tasks
               (id, project, title, instruction, status, assignee,
                priority, dependencies, acceptance_criteria, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id, payload.project, payload.title, payload.instruction,
                status.value, payload.assignee, payload.priority,
                json.dumps(payload.dependencies), payload.acceptance_criteria,
                now, now,
            ),
        )
        await self.db.commit()
        return task_id

    async def get_agent_task(self, task_id: str) -> AgentTaskRecord | None:
        cursor = await self.db.execute(
            "SELECT * FROM agent_tasks WHERE id = ?", (task_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_agent_task(row)

    async def update_agent_task(
        self,
        task_id: str,
        status: AgentTaskStatus | None = None,
        assignee: str | None = None,
        result: str | None = None,
        workspace_path: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        sets = ["updated_at = ?"]
        params: list = [now]
        if status is not None:
            sets.append("status = ?")
            params.append(status.value)
        if assignee is not None:
            sets.append("assignee = ?")
            params.append(assignee)
        if result is not None:
            sets.append("result = ?")
            params.append(result)
        if workspace_path is not None:
            sets.append("workspace_path = ?")
            params.append(workspace_path)
        params.append(task_id)
        await self.db.execute(
            f"UPDATE agent_tasks SET {', '.join(sets)} WHERE id = ?", params,
        )
        await self.db.commit()

    async def append_progress(self, task_id: str, kind: str, message: str) -> int:
        cursor = await self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM task_progress WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        seq = row["m"] + 1
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "INSERT INTO task_progress (task_id, seq, kind, message, ts)"
            " VALUES (?, ?, ?, ?, ?)",
            (task_id, seq, kind, message, now),
        )
        await self.db.commit()
        return seq

    async def list_progress(self, task_id: str) -> list[TaskProgressRecord]:
        cursor = await self.db.execute(
            "SELECT task_id, seq, kind, message, ts FROM task_progress"
            " WHERE task_id = ? ORDER BY seq",
            (task_id,),
        )
        rows = await cursor.fetchall()
        return [
            TaskProgressRecord(
                task_id=r["task_id"], seq=r["seq"], kind=r["kind"],
                message=r["message"], ts=r["ts"],
            )
            for r in rows
        ]

    async def hybrid_search(self, project: str, query: str) -> list[dict]:
        """Hybrid search combining text matching with vector cosine similarity.

        Searches inbox finding-*.md files for the project.  If no embeddings
        model is available returns text-only results.
        """
        from daemon.embeddings import EmbeddingStore, EmbeddingGenerator
        from pathlib import Path

        store = EmbeddingStore()
        await store.initialize()
        gen = EmbeddingGenerator()

        # Look for finding files in the inbox
        import os
        loom_dir = os.path.expanduser("~/.loom")
        inbox = Path(loom_dir) / "inbox" / project
        results: list[dict] = []

        if inbox.exists():
            for f_path in inbox.glob("finding-*.md"):
                try:
                    content = f_path.read_text()
                except OSError:
                    continue

                # Text match (substring)
                if query.lower() in content.lower():
                    # Also compute vector similarity
                    doc_vec = await gen.embed(content[:500])
                    query_vec = await gen.embed(query)
                    import numpy as np
                    nq = np.linalg.norm(query_vec)
                    nd = np.linalg.norm(doc_vec)
                    sim = float(np.dot(query_vec, doc_vec) / (nq * nd + 1e-8)) if nq and nd else 0.0

                    # Extract body (skip YAML frontmatter)
                    lines = content.split("\n")
                    body_start = 0
                    if lines and lines[0].strip() == "---":
                        for i, line in enumerate(lines[1:], 1):
                            if line.strip() == "---":
                                body_start = i + 1
                                break
                    body = "\n".join(lines[body_start:]).strip()[:300]

                    results.append({
                        "id": f_path.stem,
                        "text": body,
                        "score": sim,
                        "source": "finding",
                    })

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:10]


    async def list_agent_tasks(
        self, project: str, status_filter: str | None = None
    ) -> list[AgentTaskRecord]:
        if status_filter:
            cursor = await self.db.execute(
                "SELECT * FROM agent_tasks WHERE project = ? AND status = ?"
                " ORDER BY priority DESC, created_at DESC",
                (project, status_filter),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM agent_tasks WHERE project = ? AND status != 'archived'"
                " ORDER BY priority DESC, created_at DESC",
                (project,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_agent_task(r) for r in rows]

    def _all_agent_task_deps_done(self, dep_ids: list[str]) -> bool:
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            for dep_id in dep_ids:
                row = conn.execute(
                    "SELECT status FROM agent_tasks WHERE id = ?", (dep_id,)
                ).fetchone()
                if row is None or row[0] != AgentTaskStatus.DONE.value:
                    return False
            return True
        finally:
            conn.close()

    async def promote_ready_dependents(self, task_id: str) -> list[str]:
        """Promote todo tasks whose deps are all done to ready. Returns ids.

        Invoked from the PATCH /tasks handler when a task transitions to
        ``done`` — the only path that moves an agent_task to ``done`` (the
        inbox watcher's ``_handle_task`` operates on the legacy ``tasks``
        table, not ``agent_tasks``). Safe no-op (returns ``[]``) for an
        unknown ``task_id``: the project subquery yields NULL and matches no
        rows; callers already 404 before reaching here.
        """
        cursor = await self.db.execute(
            "SELECT id, dependencies FROM agent_tasks"
            " WHERE project = (SELECT project FROM agent_tasks WHERE id = ?)"
            " AND status = ?",
            (task_id, AgentTaskStatus.TODO.value),
        )
        rows = await cursor.fetchall()
        promoted: list[str] = []
        for row in rows:
            deps = json.loads(row["dependencies"] or "[]")
            if task_id in deps and self._all_agent_task_deps_done(deps):
                await self.db.execute(
                    "UPDATE agent_tasks SET status = ?, updated_at = ? WHERE id = ?",
                    (AgentTaskStatus.READY.value,
                     datetime.now(timezone.utc).isoformat(), row["id"]),
                )
                promoted.append(row["id"])
        await self.db.commit()
        return promoted

    @staticmethod
    def _row_to_agent_task(row) -> AgentTaskRecord:
        return AgentTaskRecord(
            id=row["id"],
            project=row["project"],
            title=row["title"],
            instruction=row["instruction"],
            status=AgentTaskStatus(row["status"]),
            assignee=row["assignee"],
            priority=row["priority"] or 0,
            dependencies=json.loads(row["dependencies"] or "[]"),
            acceptance_criteria=row["acceptance_criteria"] or "",
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            workspace_path=row["workspace_path"],
            result=row["result"],
        )


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
