"""SQLite-backed agent and project registry."""

import json
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from daemon.models import AgentInfo, ProjectInfo, AgentStatus
from daemon.models import (
    AgentTaskCreatePayload, AgentTaskRecord, AgentTaskStatus,
    AgentTaskUpdatePayload, TaskProgressRecord,
    AgentSettings, AgentSettingsUpdate, AgentProviderConfig,
    AgentChatRecord, AgentMessageRecord,
    TaskSuggestionRecord, SuggestionStatus,
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
        self.db_path = expanded  # store the resolved path; ~ is not auto-expanded by sqlite3
        os.makedirs(os.path.dirname(expanded), exist_ok=True)
        self.db = await aiosqlite.connect(expanded)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA journal_mode=WAL")
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
        # Migration: add structured_capabilities column if it doesn't exist.
        cursor = await self.db.execute("PRAGMA table_info(agents)")
        cols = [r[1] for r in await cursor.fetchall()]
        if "structured_capabilities" not in cols:
            await self.db.execute(
                "ALTER TABLE agents ADD COLUMN structured_capabilities TEXT DEFAULT '[]'"
            )
        if "user" not in cols:
            await self.db.execute("ALTER TABLE agents ADD COLUMN user TEXT")
        await self.db.commit()
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
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                default_model TEXT NOT NULL DEFAULT 'deepseek-chat',
                providers_json TEXT NOT NULL DEFAULT '[]',
                api_keys_json TEXT NOT NULL DEFAULT '{}'
            )
        """)
        await self.db.execute(
            "INSERT OR IGNORE INTO agent_settings (id, default_model, providers_json, api_keys_json)"
            " VALUES (1, 'deepseek-chat', ?, '{}')",
            (json.dumps([{
                "id": "deepseek",
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com",
                "model_ids": ["deepseek-chat"],
            }]),),
        )
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_chats (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                task_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_messages (
                id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_messages_chat"
            " ON agent_messages(chat_id, created_at)"
        )
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS task_suggestions (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                task_id TEXT NOT NULL,
                action_id TEXT NOT NULL,
                action_label TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0,
                prose TEXT NOT NULL DEFAULT '',
                catalog_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                jev_skipped INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_suggestions_task_status"
            " ON task_suggestions(task_id, status)"
        )
        await self.db.commit()

    async def close(self):
        if self.db:
            await self.db.close()

    # --- Agent CRUD ---

    async def upsert_agent(self, agent: AgentInfo):
        await self.db.execute(
            """INSERT OR REPLACE INTO agents
               (agent_id, agent_name, version, project, capabilities,
                structured_capabilities, status, last_heartbeat, registered_at, user)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent.agent_id,
                agent.agent_name,
                agent.version,
                agent.project,
                json.dumps(agent.capabilities),
                json.dumps([c.model_dump() for c in agent.structured_capabilities]),
                agent.status.value,
                agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
                agent.registered_at.isoformat(),
                agent.user,
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

    # Agents with no heartbeat for this long are marked offline on list.
    OFFLINE_AFTER_SECONDS = 300

    async def list_agents(self, project: Optional[str] = None, user: Optional[str] = None) -> list[AgentInfo]:
        if project and user:
            cursor = await self.db.execute(
                "SELECT * FROM agents WHERE project = ? AND user = ? ORDER BY registered_at DESC",
                (project, user),
            )
        elif project:
            cursor = await self.db.execute(
                "SELECT * FROM agents WHERE project = ? ORDER BY registered_at DESC",
                (project,),
            )
        else:
            cursor = await self.db.execute(
                "SELECT * FROM agents ORDER BY registered_at DESC"
            )
        rows = await cursor.fetchall()
        agents = [self._row_to_agent(r) for r in rows]
        await self._mark_stale_agents_offline(agents)
        return agents

    async def _mark_stale_agents_offline(self, agents: list[AgentInfo]) -> None:
        """Flip online/working agents past OFFLINE_AFTER_SECONDS to offline."""
        now = datetime.now(timezone.utc)
        changed = False
        for agent in agents:
            if agent.status == AgentStatus.OFFLINE:
                continue
            hb = agent.last_heartbeat
            if hb is None:
                continue
            if hb.tzinfo is None:
                hb = hb.replace(tzinfo=timezone.utc)
            age = (now - hb).total_seconds()
            if age > self.OFFLINE_AFTER_SECONDS:
                agent.status = AgentStatus.OFFLINE
                await self.db.execute(
                    "UPDATE agents SET status = ? WHERE agent_id = ?",
                    (AgentStatus.OFFLINE.value, agent.agent_id),
                )
                changed = True
        if changed:
            await self.db.commit()

    async def match_capability(self, project: str, need: str) -> list[AgentInfo]:
        """Find agents whose capabilities match the given need (keyword match).

        Searches both flat ``capabilities`` strings and structured
        ``AgentCapability.name`` / ``.description`` fields. Returns matching
        agents sorted by status (online first, then working, then offline).
        """
        agents = await self.list_agents(project)
        need_lower = need.lower()
        matches: list[AgentInfo] = []
        for a in agents:
            if any(need_lower in c.lower() for c in a.capabilities):
                matches.append(a)
                continue
            for sc in a.structured_capabilities:
                if need_lower in sc.name.lower() or need_lower in sc.description.lower():
                    matches.append(a)
                    break
        status_order = {"online": 0, "working": 1, "offline": 2}
        matches.sort(key=lambda a: status_order.get(a.status.value, 3))
        return matches

    async def delete_agent(self, agent_id: str) -> bool:
        """Remove an agent from the registry. Returns True if a row was deleted."""
        cursor = await self.db.execute(
            "DELETE FROM agents WHERE agent_id = ?", (agent_id,)
        )
        await self.db.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _row_to_agent(row) -> AgentInfo:
        from daemon.models import AgentCapability
        keys = row.keys()
        raw_caps = row["structured_capabilities"] if "structured_capabilities" in keys else "[]"
        try:
            sc = [AgentCapability(**c) for c in json.loads(raw_caps or "[]")]
        except (json.JSONDecodeError, TypeError):
            sc = []
        return AgentInfo(
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            version=row["version"],
            project=row["project"],
            capabilities=json.loads(row["capabilities"]),
            structured_capabilities=sc,
            status=AgentStatus(row["status"]),
            last_heartbeat=(
                datetime.fromisoformat(row["last_heartbeat"])
                if row["last_heartbeat"]
                else None
            ),
            registered_at=datetime.fromisoformat(row["registered_at"]),
            user=row["user"] if "user" in keys else None,
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
        # Cascade: agents + both task tables + progress for this project's tasks.
        cursor = await self.db.execute(
            "SELECT id FROM agent_tasks WHERE project = ?", (project_id,)
        )
        task_ids = [r[0] for r in await cursor.fetchall()]
        if task_ids:
            placeholders = ",".join("?" * len(task_ids))
            await self.db.execute(
                f"DELETE FROM task_progress WHERE task_id IN ({placeholders})",
                task_ids,
            )
        await self.db.execute(
            "DELETE FROM agent_tasks WHERE project = ?", (project_id,)
        )
        await self.db.execute(
            "DELETE FROM tasks WHERE project = ?", (project_id,)
        )
        await self.db.execute(
            "DELETE FROM agents WHERE project = ?", (project_id,)
        )
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

    async def create_agent_task(
        self,
        payload: AgentTaskCreatePayload,
        task_id: str | None = None,
        status: AgentTaskStatus | None = None,
    ) -> str:
        import uuid
        now = datetime.now(timezone.utc).isoformat()
        if task_id is None:
            task_id = str(uuid.uuid4())[:12]

        if status is None:
            status = AgentTaskStatus.READY if (
                payload.dependencies and await self._all_agent_task_deps_done(payload.dependencies)
            ) else AgentTaskStatus.TODO

        await self.db.execute(
            """INSERT OR IGNORE INTO agent_tasks
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
        from daemon.embeddings import EmbeddingGenerator
        from pathlib import Path

        gen = EmbeddingGenerator()

        # Findings are moved to .processed/ after ingest; search both places.
        # loom root is the parent of state.db (tests inject a temp db path).
        loom_dir = Path(self.db_path).expanduser().resolve().parent
        inbox = loom_dir / "inbox" / project
        results: list[dict] = []
        seen: set[str] = set()

        candidates: list[Path] = []
        if inbox.exists():
            candidates.extend(inbox.glob("finding-*.md"))
            processed = inbox / ".processed"
            if processed.exists():
                candidates.extend(processed.glob("finding-*.md"))

        for f_path in candidates:
            if f_path.stem in seen:
                continue
            seen.add(f_path.stem)
            try:
                content = f_path.read_text()
            except OSError:
                continue

            if query.lower() not in content.lower():
                continue

            doc_vec = await gen.embed(content[:500])
            query_vec = await gen.embed(query)
            import numpy as np
            nq = np.linalg.norm(query_vec)
            nd = np.linalg.norm(doc_vec)
            sim = float(np.dot(query_vec, doc_vec) / (nq * nd + 1e-8)) if nq and nd else 0.0

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

    async def _all_agent_task_deps_done(self, dep_ids: list[str]) -> bool:
        for dep_id in dep_ids:
            cursor = await self.db.execute(
                "SELECT status FROM agent_tasks WHERE id = ?", (dep_id,)
            )
            row = await cursor.fetchone()
            if row is None or row["status"] != AgentTaskStatus.DONE.value:
                return False
        return True

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
            if task_id in deps and await self._all_agent_task_deps_done(deps):
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

    # --- Loom agent settings / chats / suggestions ---

    @staticmethod
    def _mask_key(raw: str | None) -> str | None:
        if not raw:
            return None
        if len(raw) <= 4:
            return "••••"
        return "••••" + raw[-4:]

    async def get_agent_settings(self, mask_keys: bool = True) -> AgentSettings:
        cursor = await self.db.execute(
            "SELECT default_model, providers_json, api_keys_json FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        if row is None:
            return AgentSettings(
                providers=[AgentProviderConfig(
                    id="deepseek", name="DeepSeek",
                    base_url="https://api.deepseek.com",
                    model_ids=["deepseek-chat"],
                )],
            )
        providers = [AgentProviderConfig(**p) for p in json.loads(row["providers_json"] or "[]")]
        keys = json.loads(row["api_keys_json"] or "{}")
        masked = {k: self._mask_key(v) for k, v in keys.items()} if mask_keys else keys
        return AgentSettings(
            default_model=row["default_model"] or "deepseek-chat",
            providers=providers,
            api_keys_masked=masked,
        )

    async def get_raw_api_keys(self) -> dict[str, str]:
        cursor = await self.db.execute(
            "SELECT api_keys_json FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        if row is None:
            return {}
        return json.loads(row["api_keys_json"] or "{}")

    async def update_agent_settings(self, payload: AgentSettingsUpdate) -> AgentSettings:
        current = await self.get_agent_settings(mask_keys=False)
        raw_keys = await self.get_raw_api_keys()
        default_model = payload.default_model or current.default_model
        providers = payload.providers if payload.providers is not None else current.providers
        if payload.api_keys:
            for pid, key in payload.api_keys.items():
                if key and not key.startswith("••••"):
                    raw_keys[pid] = key
        await self.db.execute(
            "UPDATE agent_settings SET default_model = ?, providers_json = ?, api_keys_json = ?"
            " WHERE id = 1",
            (default_model, json.dumps([p.model_dump() for p in providers]), json.dumps(raw_keys)),
        )
        await self.db.commit()
        return await self.get_agent_settings(mask_keys=True)

    async def create_agent_chat(self, project: str, task_id: str | None = None) -> AgentChatRecord:
        import uuid
        now = datetime.now(timezone.utc).isoformat()
        chat_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO agent_chats (id, project, task_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, project, task_id, now, now),
        )
        await self.db.commit()
        return AgentChatRecord(id=chat_id, project=project, task_id=task_id, created_at=now, updated_at=now)

    async def get_agent_chat(self, chat_id: str) -> AgentChatRecord | None:
        cursor = await self.db.execute("SELECT * FROM agent_chats WHERE id = ?", (chat_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return AgentChatRecord(
            id=row["id"], project=row["project"], task_id=row["task_id"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    async def add_agent_message(self, chat_id: str, role: str, content: str) -> AgentMessageRecord:
        import uuid
        now = datetime.now(timezone.utc).isoformat()
        msg_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO agent_messages (id, chat_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (msg_id, chat_id, role, content, now),
        )
        await self.db.execute(
            "UPDATE agent_chats SET updated_at = ? WHERE id = ?", (now, chat_id),
        )
        await self.db.commit()
        return AgentMessageRecord(id=msg_id, chat_id=chat_id, role=role, content=content, created_at=now)

    async def list_agent_messages(self, chat_id: str, limit: int = 50) -> list[AgentMessageRecord]:
        cursor = await self.db.execute(
            "SELECT * FROM agent_messages WHERE chat_id = ? ORDER BY created_at ASC LIMIT ?",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            AgentMessageRecord(
                id=r["id"], chat_id=r["chat_id"], role=r["role"],
                content=r["content"], created_at=r["created_at"],
            )
            for r in rows
        ]

    async def dismiss_pending_suggestions(self, task_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE task_suggestions SET status = ?, updated_at = ?"
            " WHERE task_id = ? AND status = ?",
            (SuggestionStatus.DISMISSED.value, now, task_id, SuggestionStatus.PENDING.value),
        )
        await self.db.commit()

    async def create_task_suggestion(
        self,
        project: str,
        task_id: str,
        action_id: str,
        action_label: str,
        confidence: float,
        prose: str,
        catalog: list[dict],
        jev_skipped: bool = False,
    ) -> TaskSuggestionRecord:
        import uuid
        await self.dismiss_pending_suggestions(task_id)
        now = datetime.now(timezone.utc).isoformat()
        sid = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO task_suggestions"
            " (id, project, task_id, action_id, action_label, confidence, prose,"
            " catalog_json, status, jev_skipped, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid, project, task_id, action_id, action_label, confidence, prose,
                json.dumps(catalog), SuggestionStatus.PENDING.value,
                1 if jev_skipped else 0, now, now,
            ),
        )
        await self.db.commit()
        return TaskSuggestionRecord(
            id=sid, project=project, task_id=task_id, action_id=action_id,
            action_label=action_label, confidence=confidence, prose=prose,
            catalog_json=json.dumps(catalog), status=SuggestionStatus.PENDING,
            jev_skipped=jev_skipped, created_at=now, updated_at=now,
        )

    async def get_task_suggestion(self, suggestion_id: str) -> TaskSuggestionRecord | None:
        cursor = await self.db.execute(
            "SELECT * FROM task_suggestions WHERE id = ?", (suggestion_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_suggestion(row)

    async def get_pending_suggestion(self, task_id: str) -> TaskSuggestionRecord | None:
        cursor = await self.db.execute(
            "SELECT * FROM task_suggestions WHERE task_id = ? AND status = ?"
            " ORDER BY created_at DESC LIMIT 1",
            (task_id, SuggestionStatus.PENDING.value),
        )
        row = await cursor.fetchone()
        return self._row_to_suggestion(row) if row else None

    async def set_suggestion_status(self, suggestion_id: str, status: SuggestionStatus) -> TaskSuggestionRecord | None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE task_suggestions SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, suggestion_id),
        )
        await self.db.commit()
        return await self.get_task_suggestion(suggestion_id)

    @staticmethod
    def _row_to_suggestion(row) -> TaskSuggestionRecord:
        return TaskSuggestionRecord(
            id=row["id"], project=row["project"], task_id=row["task_id"],
            action_id=row["action_id"], action_label=row["action_label"],
            confidence=float(row["confidence"] or 0), prose=row["prose"] or "",
            catalog_json=row["catalog_json"] or "[]",
            status=SuggestionStatus(row["status"]),
            jev_skipped=bool(row["jev_skipped"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
