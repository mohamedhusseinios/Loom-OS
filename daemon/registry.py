"""SQLite-backed agent and project registry."""

import json
import logging
import aiosqlite
from datetime import datetime, timezone
from typing import Optional
from daemon.models import AgentInfo, ProjectInfo, AgentStatus
from daemon.models import (
    AgentTaskCreatePayload, AgentTaskRecord, AgentTaskStatus,
    AgentTaskUpdatePayload, TaskProgressRecord,
    AgentSettings, AgentSettingsUpdate, AgentProviderConfig,
    AgentChatRecord, AgentChatSummary, AgentMessageRecord,
    TaskSuggestionRecord, SuggestionStatus,
    AgentRunRecord,
)
from daemon.credentials_crypto import decrypt_api_keys_json, encrypt_api_keys_json
from daemon.agent_credentials import (
    DEFAULT_AGENT_PROVIDERS,
    StoredAgentCredentials,
    ensure_default_providers,
    is_masked_key,
    mask_key,
    merge_providers,
    parse_settings_row,
    sync_providers_on_update,
)

# Nullable decision telemetry. No DEFAULT so migrated rows stay NULL.
# legacy_decision_input_tokens is backfilled from jev_input_tokens only when
# that column is first added — never copied into filter_input_tokens.
_SUGGESTION_DECISION_COLUMNS = (
    ("filter_provider", "TEXT"),
    ("filter_model", "TEXT"),
    ("judgment_provider", "TEXT"),
    ("judgment_model", "TEXT"),
    ("filter_skipped", "INTEGER"),
    ("judgment_skipped", "INTEGER"),
    ("filter_skip_reason", "TEXT"),
    ("judgment_skip_reason", "TEXT"),
    ("filter_input_tokens", "INTEGER"),
    ("judgment_input_tokens", "INTEGER"),
    ("filter_latency_ms", "REAL"),
    ("judgment_latency_ms", "REAL"),
    ("effective_thresholds_json", "TEXT"),
    ("legacy_decision_input_tokens", "INTEGER"),
)

_SETTINGS_DECISION_COLUMNS = (
    ("filter_provider", "TEXT"),
    ("judgment_provider", "TEXT"),
    ("threshold_overrides_json", "TEXT"),
    ("selection_autonomy_enabled", "INTEGER NOT NULL DEFAULT 1"),
    ("autonomy_min_fit", "TEXT NOT NULL DEFAULT 'High'"),
    ("autonomy_require_margin", "INTEGER NOT NULL DEFAULT 1"),
    ("chat_provider", "TEXT NOT NULL DEFAULT 'deepseek'"),
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
        try:
            os.chmod(expanded, 0o600)
        except OSError:
            pass
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
        cursor = await self.db.execute("PRAGMA table_info(agent_tasks)")
        at_cols = [r[1] for r in await cursor.fetchall()]
        if "execution_owner" not in at_cols:
            await self.db.execute(
                "ALTER TABLE agent_tasks ADD COLUMN execution_owner TEXT"
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
                chat_provider TEXT NOT NULL DEFAULT 'deepseek',
                providers_json TEXT NOT NULL DEFAULT '[]',
                api_keys_json TEXT NOT NULL DEFAULT '{}',
                filter_provider TEXT,
                judgment_provider TEXT,
                threshold_overrides_json TEXT,
                selection_autonomy_enabled INTEGER NOT NULL DEFAULT 1,
                autonomy_min_fit TEXT NOT NULL DEFAULT 'High',
                autonomy_require_margin INTEGER NOT NULL DEFAULT 1
            )
        """)
        cursor = await self.db.execute("PRAGMA table_info(agent_settings)")
        settings_cols = [r[1] for r in await cursor.fetchall()]
        for name, ddl in _SETTINGS_DECISION_COLUMNS:
            if name not in settings_cols:
                await self.db.execute(f"ALTER TABLE agent_settings ADD COLUMN {name} {ddl}")
        await self.db.execute(
            "INSERT OR IGNORE INTO agent_settings (id, default_model, providers_json, api_keys_json)"
            " VALUES (1, 'deepseek-chat', ?, '{}')",
            (json.dumps(list(DEFAULT_AGENT_PROVIDERS)),),
        )
        await self._ensure_default_agent_providers()
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_chats (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                task_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor = await self.db.execute("PRAGMA table_info(agent_chats)")
        chat_cols = [r[1] for r in await cursor.fetchall()]
        if "archived_at" not in chat_cols:
            await self.db.execute(
                "ALTER TABLE agent_chats ADD COLUMN archived_at TEXT"
            )
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
        cursor = await self.db.execute("PRAGMA table_info(agent_messages)")
        msg_cols = [r[1] for r in await cursor.fetchall()]
        if "reasoning_content" not in msg_cols:
            await self.db.execute(
                "ALTER TABLE agent_messages ADD COLUMN reasoning_content TEXT"
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
                jev_input_tokens INTEGER NOT NULL DEFAULT 0,
                llm_prompt_tokens INTEGER NOT NULL DEFAULT 0,
                llm_completion_tokens INTEGER NOT NULL DEFAULT 0,
                escalated INTEGER NOT NULL DEFAULT 0,
                context_hash TEXT NOT NULL DEFAULT '',
                filter_provider TEXT,
                filter_model TEXT,
                judgment_provider TEXT,
                judgment_model TEXT,
                filter_skipped INTEGER,
                judgment_skipped INTEGER,
                filter_skip_reason TEXT,
                judgment_skip_reason TEXT,
                filter_input_tokens INTEGER,
                judgment_input_tokens INTEGER,
                filter_latency_ms REAL,
                judgment_latency_ms REAL,
                effective_thresholds_json TEXT,
                legacy_decision_input_tokens INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_task_suggestions_task_status"
            " ON task_suggestions(task_id, status)"
        )
        # Migration: usage / escalation columns on existing DBs.
        cursor = await self.db.execute("PRAGMA table_info(task_suggestions)")
        sug_cols = [r[1] for r in await cursor.fetchall()]
        had_jev_input_tokens = "jev_input_tokens" in sug_cols
        for name, ddl in (
            ("jev_input_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("llm_prompt_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("llm_completion_tokens", "INTEGER NOT NULL DEFAULT 0"),
            ("escalated", "INTEGER NOT NULL DEFAULT 0"),
            ("context_hash", "TEXT NOT NULL DEFAULT ''"),
        ):
            if name not in sug_cols:
                await self.db.execute(f"ALTER TABLE task_suggestions ADD COLUMN {name} {ddl}")
        added_legacy_tokens = False
        for name, ddl in _SUGGESTION_DECISION_COLUMNS:
            if name not in sug_cols:
                await self.db.execute(f"ALTER TABLE task_suggestions ADD COLUMN {name} {ddl}")
                if name == "legacy_decision_input_tokens":
                    added_legacy_tokens = True
        # Old rows only. Do not copy jev_input_tokens into filter_input_tokens,
        # and do not repeat this after the column exists (new rows keep legacy NULL).
        if added_legacy_tokens and had_jev_input_tokens:
            await self.db.execute(
                "UPDATE task_suggestions SET legacy_decision_input_tokens = jev_input_tokens"
                " WHERE legacy_decision_input_tokens IS NULL"
            )
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                project TEXT NOT NULL,
                family_id TEXT NOT NULL DEFAULT 'react',
                modifier_ids_json TEXT NOT NULL DEFAULT '[]',
                schema_version INTEGER NOT NULL DEFAULT 1,
                pattern_versions_json TEXT NOT NULL DEFAULT '{}',
                recommended_json TEXT,
                chosen_source TEXT,
                user_override INTEGER NOT NULL DEFAULT 0,
                stage1_profile_json TEXT,
                fit_levels_json TEXT,
                selection_scores_json TEXT,
                selection_filter_provider TEXT,
                selection_judgment_provider TEXT,
                selection_filter_skipped INTEGER,
                selection_judgment_skipped INTEGER,
                selection_skip_reason TEXT,
                status TEXT NOT NULL,
                worktree_path TEXT,
                run_dir TEXT,
                step_limit INTEGER NOT NULL DEFAULT 40,
                token_limit INTEGER NOT NULL DEFAULT 100000,
                cost_limit REAL NOT NULL DEFAULT 1.0,
                steps_used INTEGER NOT NULL DEFAULT 0,
                tokens_used INTEGER NOT NULL DEFAULT 0,
                cost_used REAL NOT NULL DEFAULT 0,
                stop_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        cursor = await self.db.execute("PRAGMA table_info(agent_runs)")
        run_cols = [r[1] for r in await cursor.fetchall()]
        for name, ddl in (
            ("schema_version", "INTEGER NOT NULL DEFAULT 1"),
            ("pattern_versions_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("recommended_json", "TEXT"),
            ("chosen_source", "TEXT"),
            ("user_override", "INTEGER NOT NULL DEFAULT 0"),
            ("stage1_profile_json", "TEXT"),
            ("fit_levels_json", "TEXT"),
            ("selection_scores_json", "TEXT"),
            ("selection_filter_provider", "TEXT"),
            ("selection_judgment_provider", "TEXT"),
            ("selection_filter_skipped", "INTEGER"),
            ("selection_judgment_skipped", "INTEGER"),
            ("selection_skip_reason", "TEXT"),
        ):
            if name not in run_cols:
                await self.db.execute(f"ALTER TABLE agent_runs ADD COLUMN {name} {ddl}")
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_task ON agent_runs(task_id)"
        )
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_runs_project_status"
            " ON agent_runs(project, status)"
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

    async def claim_task_execution(self, task_id: str, owner: str) -> bool:
        """Atomically claim a Running task for execution. Returns True if claimed.

        Only succeeds when status is ``running``. Re-claim by the same owner
        succeeds (one-shot worker after daemon claim).
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = await self.db.execute(
            "UPDATE agent_tasks SET execution_owner = ?, updated_at = ?"
            " WHERE id = ? AND status = ?"
            " AND (execution_owner IS NULL OR execution_owner = ''"
            " OR execution_owner = ?)",
            (owner, now, task_id, AgentTaskStatus.RUNNING.value, owner),
        )
        await self.db.commit()
        return cursor.rowcount > 0

    async def release_task_execution(self, task_id: str, owner: str | None = None) -> None:
        """Clear execution lease. If owner is set, only that owner can release."""
        if owner is None:
            await self.db.execute(
                "UPDATE agent_tasks SET execution_owner = NULL, updated_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), task_id),
            )
        else:
            await self.db.execute(
                "UPDATE agent_tasks SET execution_owner = NULL, updated_at = ?"
                " WHERE id = ? AND execution_owner = ?",
                (datetime.now(timezone.utc).isoformat(), task_id, owner),
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
        import numpy as np
        from pathlib import Path

        from daemon.embeddings import EmbeddingGenerator

        gen = EmbeddingGenerator()
        query_vec = await gen.embed(query)

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

        q_lower = query.lower()
        nq = float(np.linalg.norm(query_vec))
        for f_path in candidates:
            if f_path.stem in seen:
                continue
            seen.add(f_path.stem)
            try:
                content = f_path.read_text()
            except OSError:
                continue

            if q_lower not in content.lower():
                continue

            doc_vec = await gen.embed(content[:500])
            nd = float(np.linalg.norm(doc_vec))
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
        keys = row.keys()
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
            execution_owner=row["execution_owner"] if "execution_owner" in keys else None,
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
        return mask_key(raw)

    def _settings_from_row(self, row) -> StoredAgentCredentials:
        if row is None:
            return parse_settings_row(
                "deepseek-chat",
                list(DEFAULT_AGENT_PROVIDERS),
                {},
                "deepseek",
            )
        keys = set(row.keys())
        chat = row["chat_provider"] if "chat_provider" in keys else "deepseek"
        raw_keys = row["api_keys_json"]
        if isinstance(raw_keys, str):
            raw_keys = decrypt_api_keys_json(raw_keys)
        return parse_settings_row(
            row["default_model"], row["providers_json"], raw_keys, chat,
        )

    @staticmethod
    def _threshold_overrides_from_raw(raw: str | None) -> dict | None:
        if not raw:
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _decision_settings_from_row(row) -> tuple[str | None, str | None, dict | None]:
        if row is None:
            return None, None, None
        keys = set(row.keys())
        filt = row["filter_provider"] if "filter_provider" in keys else None
        judg = row["judgment_provider"] if "judgment_provider" in keys else None
        raw = row["threshold_overrides_json"] if "threshold_overrides_json" in keys else None
        return filt, judg, AgentRegistry._threshold_overrides_from_raw(raw)

    def _agent_settings_view(self, creds: StoredAgentCredentials, mask_keys: bool, filter_provider: str | None = None, judgment_provider: str | None = None, threshold_overrides: dict | None = None, selection_autonomy_enabled: bool = True, autonomy_min_fit: str = "High", autonomy_require_margin: bool = True) -> AgentSettings:
        providers = [AgentProviderConfig(**p) for p in creds.providers]
        masked = creds.masked_keys() if mask_keys else dict(creds.keys)
        return AgentSettings(
            default_model=creds.default_model,
            chat_provider=creds.chat_provider or "deepseek",
            providers=providers,
            api_keys_masked=masked,
            has_keys=creds.has_keys(),
            filter_provider=filter_provider,
            judgment_provider=judgment_provider,
            threshold_overrides=threshold_overrides,
            selection_autonomy_enabled=selection_autonomy_enabled,
            autonomy_min_fit=autonomy_min_fit,
            autonomy_require_margin=autonomy_require_margin,
        )

    async def _ensure_default_agent_providers(self) -> None:
        """Migration: add built-in provider rows missing from the singleton."""
        cursor = await self.db.execute(
            "SELECT providers_json FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        if row is None:
            return
        current = json.loads(row["providers_json"] or "[]")
        ensured = ensure_default_providers(current)
        if ensured != current:
            await self.db.execute(
                "UPDATE agent_settings SET providers_json = ? WHERE id = 1",
                (json.dumps(ensured),),
            )
            await self.db.commit()

    async def get_agent_settings(self, mask_keys: bool = True) -> AgentSettings:
        cursor = await self.db.execute(
            "SELECT default_model, chat_provider, providers_json, api_keys_json,"
            " filter_provider, judgment_provider, threshold_overrides_json,"
            " selection_autonomy_enabled, autonomy_min_fit, autonomy_require_margin"
            " FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        filt, judg, overrides = self._decision_settings_from_row(row)
        return self._agent_settings_view(
            self._settings_from_row(row), mask_keys,
            filter_provider=filt, judgment_provider=judg, threshold_overrides=overrides,
            selection_autonomy_enabled=bool(row["selection_autonomy_enabled"]),
            autonomy_min_fit=row["autonomy_min_fit"],
            autonomy_require_margin=bool(row["autonomy_require_margin"]),
        )

    async def get_raw_api_keys(self) -> dict[str, str]:
        cursor = await self.db.execute(
            "SELECT api_keys_json FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        if row is None:
            return {}
        plain = decrypt_api_keys_json(row["api_keys_json"] or "{}")
        keys = json.loads(plain or "{}")
        return {k: v for k, v in keys.items() if v}

    async def update_agent_settings(self, payload: AgentSettingsUpdate) -> AgentSettings:
        cursor = await self.db.execute(
            "SELECT default_model, chat_provider, providers_json, api_keys_json,"
            " filter_provider, judgment_provider, threshold_overrides_json,"
            " selection_autonomy_enabled, autonomy_min_fit, autonomy_require_margin"
            " FROM agent_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        creds = self._settings_from_row(row)
        default_model = payload.default_model or creds.default_model
        chat_provider = creds.chat_provider or "deepseek"
        if payload.chat_provider is not None and str(payload.chat_provider).strip():
            chat_provider = str(payload.chat_provider).strip()
        removed_custom: list[str] = []
        if payload.providers is not None:
            providers, removed_custom = sync_providers_on_update(creds.providers, payload.providers)
        else:
            providers = creds.providers
        removed_ids = set(payload.remove_provider_ids or [])
        if removed_ids:
            providers = [p for p in providers if p.get("id") not in removed_ids]
        raw_keys = dict(creds.keys)
        for pid in removed_custom:
            raw_keys.pop(pid, None)
        if payload.api_keys is not None:
            for pid, key in payload.api_keys.items():
                if key is None or is_masked_key(key):
                    continue
                if key == "":
                    raw_keys.pop(pid, None)
                else:
                    raw_keys[pid] = key
        for pid in removed_ids:
            raw_keys.pop(pid, None)
        provider_ids = {p.get("id") for p in providers}
        if chat_provider not in provider_ids:
            chat_provider = "deepseek"
        filt, judg, _overrides = self._decision_settings_from_row(row)
        raw_overrides = None
        if row is not None and "threshold_overrides_json" in row.keys():
            raw_overrides = row["threshold_overrides_json"]
        if payload.filter_provider is not None:
            filt = payload.filter_provider
        if payload.judgment_provider is not None:
            judg = payload.judgment_provider
        if payload.threshold_overrides is not None:
            raw_overrides = json.dumps(payload.threshold_overrides)
        selection_autonomy_enabled = bool(row["selection_autonomy_enabled"])
        autonomy_min_fit = row["autonomy_min_fit"]
        autonomy_require_margin = bool(row["autonomy_require_margin"])
        if payload.selection_autonomy_enabled is not None:
            selection_autonomy_enabled = payload.selection_autonomy_enabled
        if payload.autonomy_min_fit is not None:
            autonomy_min_fit = payload.autonomy_min_fit
        if payload.autonomy_require_margin is not None:
            autonomy_require_margin = payload.autonomy_require_margin
        await self.db.execute(
            "UPDATE agent_settings SET default_model = ?, chat_provider = ?, providers_json = ?, api_keys_json = ?,"
            " filter_provider = ?, judgment_provider = ?, threshold_overrides_json = ?,"
            " selection_autonomy_enabled = ?, autonomy_min_fit = ?, autonomy_require_margin = ?"
            " WHERE id = 1",
            (
                default_model, chat_provider, json.dumps(providers), encrypt_api_keys_json(json.dumps(raw_keys)), filt, judg,
                raw_overrides, selection_autonomy_enabled, autonomy_min_fit,
                autonomy_require_margin,
            ),
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
            archived_at=row["archived_at"] if "archived_at" in row.keys() else None,
        )

    async def add_agent_message(self, chat_id: str, role: str, content: str, reasoning_content: str | None = None) -> AgentMessageRecord:
        import uuid
        now = datetime.now(timezone.utc).isoformat()
        msg_id = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO agent_messages (id, chat_id, role, content, created_at, reasoning_content) VALUES (?, ?, ?, ?, ?, ?)",
            (msg_id, chat_id, role, content, now, reasoning_content),
        )
        await self.db.execute(
            "UPDATE agent_chats SET updated_at = ? WHERE id = ?", (now, chat_id),
        )
        await self.db.commit()
        return AgentMessageRecord(id=msg_id, chat_id=chat_id, role=role, content=content, created_at=now, reasoning_content=reasoning_content)


    async def list_agent_chats(self, project: str, task_id: str | None = None, limit: int = 50, archived: bool = False) -> list[AgentChatSummary]:
        """List chats for a project, newest first, with last-message preview.

        When ``task_id`` is None, only project-scoped chats (task_id IS NULL) are returned.
        When set, only chats for that task are returned.
        """
        if task_id is None:
            where = "c.project = ? AND c.task_id IS NULL"
            params: list = [project, limit]
        else:
            where = "c.project = ? AND c.task_id = ?"
            params = [project, task_id, limit]
        arch_clause = "c.archived_at IS NOT NULL" if archived else "c.archived_at IS NULL"
        where = f"{where} AND {arch_clause}"
        cursor = await self.db.execute(
            "SELECT c.id, c.project, c.task_id, c.created_at, c.updated_at, c.archived_at, "
            "  COALESCE(("
            "    SELECT m.content FROM agent_messages m"
            "    WHERE m.chat_id = c.id"
            "    ORDER BY m.created_at DESC LIMIT 1"
            "  ), '') AS preview "
            f"FROM agent_chats c WHERE {where} "
            "ORDER BY c.updated_at DESC LIMIT ?",
            params,
        )
        rows = await cursor.fetchall()
        return [
            AgentChatSummary(
                id=r["id"], project=r["project"], task_id=r["task_id"],
                created_at=r["created_at"], updated_at=r["updated_at"],
                preview=(r["preview"] or "")[:120],
                archived_at=r["archived_at"] if "archived_at" in r.keys() else None,
            )
            for r in rows
        ]

    async def archive_agent_chat(self, chat_id: str) -> AgentChatRecord | None:
        chat = await self.get_agent_chat(chat_id)
        if chat is None:
            return None
        if chat.archived_at is None:
            now = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE agent_chats SET archived_at = ? WHERE id = ?",
                (now, chat_id),
            )
            await self.db.commit()
            return await self.get_agent_chat(chat_id)
        return chat

    async def unarchive_agent_chat(self, chat_id: str) -> AgentChatRecord | None:
        chat = await self.get_agent_chat(chat_id)
        if chat is None:
            return None
        if chat.archived_at is not None:
            await self.db.execute(
                "UPDATE agent_chats SET archived_at = NULL WHERE id = ?",
                (chat_id,),
            )
            await self.db.commit()
            return await self.get_agent_chat(chat_id)
        return chat

    async def delete_agent_chat(self, chat_id: str) -> bool:
        chat = await self.get_agent_chat(chat_id)
        if chat is None:
            return False
        await self.db.execute("DELETE FROM agent_messages WHERE chat_id = ?", (chat_id,))
        await self.db.execute("DELETE FROM agent_chats WHERE id = ?", (chat_id,))
        await self.db.commit()
        return True

    async def agent_chat_summary(self, chat_id: str) -> AgentChatSummary | None:
        chat = await self.get_agent_chat(chat_id)
        if chat is None:
            return None
        cursor = await self.db.execute(
            "SELECT content FROM agent_messages WHERE chat_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (chat_id,),
        )
        row = await cursor.fetchone()
        preview = ((row["content"] if row else "") or "")[:120]
        return AgentChatSummary(
            id=chat.id, project=chat.project, task_id=chat.task_id,
            created_at=chat.created_at, updated_at=chat.updated_at,
            preview=preview, archived_at=chat.archived_at,
        )

    async def list_agent_messages(self, chat_id: str, limit: int = 50) -> list[AgentMessageRecord]:
        """Return the latest ``limit`` messages in chronological order."""
        cursor = await self.db.execute(
            "SELECT * FROM ("
            " SELECT * FROM agent_messages WHERE chat_id = ?"
            " ORDER BY created_at DESC LIMIT ?"
            ") AS recent ORDER BY created_at ASC",
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            AgentMessageRecord(
                id=r["id"], chat_id=r["chat_id"], role=r["role"],
                content=r["content"], created_at=r["created_at"],
                reasoning_content=r["reasoning_content"] if "reasoning_content" in r.keys() else None,
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

    async def create_task_suggestion(self, project: str, task_id: str, action_id: str, action_label: str, confidence: float, prose: str, catalog: list[dict], jev_skipped: bool = False, jev_input_tokens: int = 0, llm_prompt_tokens: int = 0, llm_completion_tokens: int = 0, escalated: bool = False, context_hash: str = "", filter_provider: str | None = None, filter_model: str | None = None, judgment_provider: str | None = None, judgment_model: str | None = None, filter_skipped: bool | None = None, judgment_skipped: bool | None = None, filter_skip_reason: str | None = None, judgment_skip_reason: str | None = None, filter_input_tokens: int | None = None, judgment_input_tokens: int | None = None, filter_latency_ms: float | None = None, judgment_latency_ms: float | None = None, effective_thresholds_json: str | None = None) -> TaskSuggestionRecord:
        import uuid

        def _bit(value: bool | None) -> int | None:
            if value is None:
                return None
            return 1 if value else 0

        def _opt_int(value: int | None) -> int | None:
            if value is None:
                return None
            return int(value)

        await self.dismiss_pending_suggestions(task_id)
        now = datetime.now(timezone.utc).isoformat()
        sid = str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO task_suggestions"
            " (id, project, task_id, action_id, action_label, confidence, prose,"
            " catalog_json, status, jev_skipped, jev_input_tokens,"
            " llm_prompt_tokens, llm_completion_tokens, escalated, context_hash,"
            " filter_provider, filter_model, judgment_provider, judgment_model,"
            " filter_skipped, judgment_skipped, filter_skip_reason, judgment_skip_reason,"
            " filter_input_tokens, judgment_input_tokens, filter_latency_ms, judgment_latency_ms,"
            " effective_thresholds_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                sid, project, task_id, action_id, action_label, confidence, prose,
                json.dumps(catalog), SuggestionStatus.PENDING.value,
                1 if jev_skipped else 0, int(jev_input_tokens or 0),
                int(llm_prompt_tokens or 0), int(llm_completion_tokens or 0),
                1 if escalated else 0, context_hash or "",
                filter_provider, filter_model, judgment_provider, judgment_model,
                _bit(filter_skipped), _bit(judgment_skipped),
                filter_skip_reason, judgment_skip_reason,
                _opt_int(filter_input_tokens), _opt_int(judgment_input_tokens),
                filter_latency_ms, judgment_latency_ms,
                effective_thresholds_json, now, now,
            ),
        )
        await self.db.commit()
        return TaskSuggestionRecord(
            id=sid, project=project, task_id=task_id, action_id=action_id,
            action_label=action_label, confidence=confidence, prose=prose,
            catalog_json=json.dumps(catalog), status=SuggestionStatus.PENDING,
            jev_skipped=jev_skipped, jev_input_tokens=int(jev_input_tokens or 0),
            llm_prompt_tokens=int(llm_prompt_tokens or 0),
            llm_completion_tokens=int(llm_completion_tokens or 0),
            escalated=escalated, context_hash=context_hash or "",
            filter_provider=filter_provider, filter_model=filter_model,
            judgment_provider=judgment_provider, judgment_model=judgment_model,
            filter_skipped=filter_skipped, judgment_skipped=judgment_skipped,
            filter_skip_reason=filter_skip_reason, judgment_skip_reason=judgment_skip_reason,
            filter_input_tokens=_opt_int(filter_input_tokens),
            judgment_input_tokens=_opt_int(judgment_input_tokens),
            filter_latency_ms=filter_latency_ms, judgment_latency_ms=judgment_latency_ms,
            effective_thresholds_json=effective_thresholds_json,
            created_at=now, updated_at=now,
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

    async def suggestion_cost_summary(self, project: str) -> dict:
        cursor = await self.db.execute(
            "SELECT * FROM task_suggestions WHERE project = ?",
            (project,),
        )
        rows = await cursor.fetchall()
        records = [self._row_to_suggestion(r) for r in rows]
        from daemon.agent_cost import summarize_suggestions
        return summarize_suggestions(records)


    async def set_suggestion_status(self, suggestion_id: str, status: SuggestionStatus) -> TaskSuggestionRecord | None:
        now = datetime.now(timezone.utc).isoformat()
        await self.db.execute(
            "UPDATE task_suggestions SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, suggestion_id),
        )
        await self.db.commit()
        record = await self.get_task_suggestion(suggestion_id)
        if record is not None:
            logging.getLogger("loom.registry").info(
                "suggestion outcome id=%s task=%s status=%s action=%s "
                "jev_input_tokens=%s llm_prompt_tokens=%s llm_completion_tokens=%s "
                "jev_skipped=%s escalated=%s",
                record.id, record.task_id, record.status.value, record.action_id,
                record.jev_input_tokens, record.llm_prompt_tokens,
                record.llm_completion_tokens, record.jev_skipped, record.escalated,
            )
        return record

    @staticmethod
    def _row_to_suggestion(row) -> TaskSuggestionRecord:
        keys = row.keys()
        def _int(name: str) -> int:
            if name not in keys:
                return 0
            try:
                return int(row[name] or 0)
            except (TypeError, ValueError):
                return 0
        def _opt_int(name: str) -> int | None:
            if name not in keys or row[name] is None:
                return None
            try:
                return int(row[name])
            except (TypeError, ValueError):
                return None
        def _opt_float(name: str) -> float | None:
            if name not in keys or row[name] is None:
                return None
            try:
                return float(row[name])
            except (TypeError, ValueError):
                return None
        def _opt_bool(name: str) -> bool | None:
            if name not in keys or row[name] is None:
                return None
            return bool(row[name])
        def _opt_text(name: str) -> str | None:
            if name not in keys or row[name] is None:
                return None
            return row[name]
        return TaskSuggestionRecord(
            id=row["id"], project=row["project"], task_id=row["task_id"],
            action_id=row["action_id"], action_label=row["action_label"],
            confidence=float(row["confidence"] or 0), prose=row["prose"] or "",
            catalog_json=row["catalog_json"] or "[]",
            status=SuggestionStatus(row["status"]),
            jev_skipped=bool(row["jev_skipped"]),
            jev_input_tokens=_int("jev_input_tokens"),
            llm_prompt_tokens=_int("llm_prompt_tokens"),
            llm_completion_tokens=_int("llm_completion_tokens"),
            escalated=bool(_int("escalated")),
            context_hash=(row["context_hash"] if "context_hash" in keys and row["context_hash"] else ""),
            filter_provider=_opt_text("filter_provider"),
            filter_model=_opt_text("filter_model"),
            judgment_provider=_opt_text("judgment_provider"),
            judgment_model=_opt_text("judgment_model"),
            filter_skipped=_opt_bool("filter_skipped"),
            judgment_skipped=_opt_bool("judgment_skipped"),
            filter_skip_reason=_opt_text("filter_skip_reason"),
            judgment_skip_reason=_opt_text("judgment_skip_reason"),
            filter_input_tokens=_opt_int("filter_input_tokens"),
            judgment_input_tokens=_opt_int("judgment_input_tokens"),
            filter_latency_ms=_opt_float("filter_latency_ms"),
            judgment_latency_ms=_opt_float("judgment_latency_ms"),
            effective_thresholds_json=_opt_text("effective_thresholds_json"),
            legacy_decision_input_tokens=_opt_int("legacy_decision_input_tokens"),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    async def create_agent_run(self, *, task_id: str, project: str, run_dir: str, worktree_path: str | None = None, family_id: str = "react", modifier_ids_json: str = "[]", schema_version: int = 1, pattern_versions_json: str = "{}", recommended_json: str | None = None, chosen_source: str | None = None, user_override: bool = False, stage1_profile_json: str | None = None, fit_levels_json: str | None = None, selection_scores_json: str | None = None, selection_filter_provider: str | None = None, selection_judgment_provider: str | None = None, selection_filter_skipped: bool | None = None, selection_judgment_skipped: bool | None = None, selection_skip_reason: str | None = None, status: str = "running", step_limit: int = 40, token_limit: int = 100000, cost_limit: float = 1.0, run_id: str | None = None) -> AgentRunRecord:
        import uuid
        now = datetime.now(timezone.utc).isoformat()
        run_id = run_id or str(uuid.uuid4())
        await self.db.execute(
            "INSERT INTO agent_runs (id, task_id, project, family_id, modifier_ids_json,"
            " schema_version, pattern_versions_json, recommended_json, chosen_source, user_override,"
            " stage1_profile_json, fit_levels_json, selection_scores_json, selection_filter_provider,"
            " selection_judgment_provider, selection_filter_skipped, selection_judgment_skipped,"
            " selection_skip_reason, status, worktree_path, run_dir, step_limit, token_limit,"
            " cost_limit, steps_used, tokens_used, cost_used, stop_reason, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " 0, 0, 0, NULL, ?, ?)",
            (
                run_id, task_id, project, family_id, modifier_ids_json, schema_version,
                pattern_versions_json, recommended_json, chosen_source, user_override,
                stage1_profile_json, fit_levels_json, selection_scores_json,
                selection_filter_provider, selection_judgment_provider, selection_filter_skipped,
                selection_judgment_skipped, selection_skip_reason, status, worktree_path, run_dir,
                step_limit, token_limit, cost_limit, now, now,
            ),
        )
        await self.db.commit()
        return AgentRunRecord(
            id=run_id, task_id=task_id, project=project, family_id=family_id,
            modifier_ids_json=modifier_ids_json, schema_version=schema_version,
            pattern_versions_json=pattern_versions_json, recommended_json=recommended_json,
            chosen_source=chosen_source, user_override=user_override,
            stage1_profile_json=stage1_profile_json, fit_levels_json=fit_levels_json,
            selection_scores_json=selection_scores_json,
            selection_filter_provider=selection_filter_provider,
            selection_judgment_provider=selection_judgment_provider,
            selection_filter_skipped=selection_filter_skipped,
            selection_judgment_skipped=selection_judgment_skipped,
            selection_skip_reason=selection_skip_reason, status=status, worktree_path=worktree_path,
            run_dir=run_dir, step_limit=step_limit, token_limit=token_limit, cost_limit=cost_limit,
            steps_used=0, tokens_used=0, cost_used=0.0, stop_reason=None,
            created_at=now, updated_at=now,
        )

    async def get_agent_run(self, run_id: str) -> AgentRunRecord | None:
        cursor = await self.db.execute("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_agent_run(row)

    async def list_agent_runs(self, project: str | None = None, task_id: str | None = None, status: str | None = None) -> list[AgentRunRecord]:
        clauses: list[str] = []
        params: list = []
        if project is not None:
            clauses.append("project = ?")
            params.append(project)
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor = await self.db.execute(
            f"SELECT * FROM agent_runs{where} ORDER BY created_at ASC", params,
        )
        rows = await cursor.fetchall()
        return [self._row_to_agent_run(row) for row in rows]

    async def update_agent_run(self, run_id: str, status: str | None = None, stop_reason: str | None = None, steps_used: int | None = None, tokens_used: int | None = None, cost_used: float | None = None, worktree_path: str | None = None, schema_version: int | None = None, pattern_versions_json: str | None = None, recommended_json: str | None = None, chosen_source: str | None = None, user_override: bool | None = None, stage1_profile_json: str | None = None, fit_levels_json: str | None = None, selection_scores_json: str | None = None, selection_filter_provider: str | None = None, selection_judgment_provider: str | None = None, selection_filter_skipped: bool | None = None, selection_judgment_skipped: bool | None = None, selection_skip_reason: str | None = None, if_status: str | None = None) -> AgentRunRecord | None:
        current = await self.get_agent_run(run_id)
        if current is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        sets = ["updated_at = ?"]
        params: list = [now]
        for name, value in (
            ("status", status),
            ("stop_reason", stop_reason),
            ("steps_used", steps_used),
            ("tokens_used", tokens_used),
            ("cost_used", cost_used),
            ("worktree_path", worktree_path),
            ("schema_version", schema_version),
            ("pattern_versions_json", pattern_versions_json),
            ("recommended_json", recommended_json),
            ("chosen_source", chosen_source),
            ("user_override", user_override),
            ("stage1_profile_json", stage1_profile_json),
            ("fit_levels_json", fit_levels_json),
            ("selection_scores_json", selection_scores_json),
            ("selection_filter_provider", selection_filter_provider),
            ("selection_judgment_provider", selection_judgment_provider),
            ("selection_filter_skipped", selection_filter_skipped),
            ("selection_judgment_skipped", selection_judgment_skipped),
            ("selection_skip_reason", selection_skip_reason),
        ):
            if value is not None:
                sets.append(f"{name} = ?")
                params.append(value)
        params.append(run_id)
        sql = f"UPDATE agent_runs SET {', '.join(sets)} WHERE id = ?"
        if if_status is not None:
            sql += " AND status = ?"
            params.append(if_status)
        await self.db.execute(sql, params)
        await self.db.commit()
        return await self.get_agent_run(run_id)

    def _row_to_agent_run(self, row) -> AgentRunRecord:
        return AgentRunRecord(
            id=row["id"], task_id=row["task_id"], project=row["project"],
            family_id=row["family_id"] or "react",
            modifier_ids_json=row["modifier_ids_json"] or "[]",
            schema_version=int(row["schema_version"]),
            pattern_versions_json=row["pattern_versions_json"] or "{}",
            recommended_json=row["recommended_json"],
            chosen_source=row["chosen_source"],
            user_override=bool(row["user_override"]),
            stage1_profile_json=row["stage1_profile_json"],
            fit_levels_json=row["fit_levels_json"],
            selection_scores_json=row["selection_scores_json"],
            selection_filter_provider=row["selection_filter_provider"],
            selection_judgment_provider=row["selection_judgment_provider"],
            selection_filter_skipped=(bool(row["selection_filter_skipped"]) if row["selection_filter_skipped"] is not None else None),
            selection_judgment_skipped=(bool(row["selection_judgment_skipped"]) if row["selection_judgment_skipped"] is not None else None),
            selection_skip_reason=row["selection_skip_reason"],
            status=row["status"],
            worktree_path=row["worktree_path"],
            run_dir=row["run_dir"] or "",
            step_limit=int(row["step_limit"] or 0),
            token_limit=int(row["token_limit"] or 0),
            cost_limit=float(row["cost_limit"] or 0),
            steps_used=int(row["steps_used"] or 0),
            tokens_used=int(row["tokens_used"] or 0),
            cost_used=float(row["cost_used"] or 0),
            stop_reason=row["stop_reason"],
            created_at=row["created_at"], updated_at=row["updated_at"],
        )
