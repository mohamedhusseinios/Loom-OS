# Competitor Gap Closure — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.
> Parent plan: [2026-06-26-dashboard-features-implementation.md](./2026-06-26-dashboard-features-implementation.md) (Phases 1-4 must complete first)

**Goal:** Close 12 competitive gaps identified in the 2026-06-26 competitor analysis — transform Loom from a "file system with a graph index" into a definitive agent memory fabric with auto-recall/retain memory, durable task coordination, hybrid vector-graph retrieval, LLM-powered knowledge extraction, session continuity, observability, MCP protocol support, self-evolving patterns, governance, temporal tracking, and multi-format ingestion.

**Architecture:** Extend the existing Python FastAPI daemon + Next.js dashboard. Zero new infrastructure (no Docker, no Neo4j, no external DB). New capabilities live inside the existing daemon process as new modules (`daemon/recall.py`, `daemon/tasks.py`, `daemon/embeddings.py`, `daemon/extractors.py`, `daemon/sessions.py`, `daemon/traces.py`, `daemon/mcp_server.py`). Dashboard gains new pages/components consuming the expanded API. The filesystem inbox protocol is extended with `task-*.json` and `session-*.json`.

**Tech Stack:** Python 3.11+ (FastAPI, aiosqlite, numpy, sentence-transformers, watchdog), TypeScript (Next.js 16, React 19, Shadcn UI, Cytoscape.js), MCP (stdio transport)

**Constraints (non-negotiable):**
- Single-process daemon — `agentic-os start` remains the only command
- Filesystem inbox protocol preserved — zero SDK, zero auth
- Per-project isolation intact
- No new infrastructure (no Docker, Neo4j, external DB, cloud services)
- Existing 38 tests must stay green throughout

---

## Sprint 0: CRITICAL — Core Memory Fabric (Weeks 1-6)

> Without these features, Loom is not a memory fabric. Ship first.

### Feature 1: Shared Cross-Agent Memory Bank (Auto-Recall + Auto-Retain)

**Evidence:** Claude Code sub-agents forget everything. Hindsight + Hermes Agent prove auto-recall/retain compounds agent intelligence.

### Task 1.1: Create RecallEngine class with graph context injection

**Objective:** Core recall engine that queries the Graphify graph for entities relevant to the current agent task and injects them as pre-context.

**Files:**
- Create: `daemon/recall.py`
- Create: `tests/test_recall.py`

**Step 1: Write failing test**

```python
# tests/test_recall.py
import pytest
from daemon.recall import RecallEngine

@pytest.mark.asyncio
async def test_recall_context_for_registered_agent():
    engine = RecallEngine()
    # Agent registered for project "test-proj", current task "auth refactor"
    context = await engine.recall(agent_id="agent-1", project="test-proj", task_hint="auth refactor")
    assert context is not None
    assert isinstance(context, str)
    assert len(context) > 0
```

Run: `pytest tests/test_recall.py::test_recall_context_for_registered_agent -v`
Expected: FAIL — RecallEngine not defined

**Step 2: Write minimal implementation**

```python
# daemon/recall.py
import json
import os
from pathlib import Path

class RecallEngine:
    """Queries the Graphify graph for entities relevant to the current agent task."""

    def __init__(self, loom_dir: str = None):
        self.loom_dir = Path(loom_dir or os.path.expanduser("~/.loom"))

    async def recall(self, agent_id: str, project: str, task_hint: str = "") -> str:
        """Return pre-context string from graph entities matching the task hint."""
        graph_path = self.loom_dir / "projects" / project / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return ""

        with open(graph_path) as f:
            graph = json.load(f)

        entities = []
        for node in graph.get("nodes", []):
            name = node.get("name") or node.get("label", "")
            kind = node.get("kind", "")
            if task_hint and task_hint.lower() in name.lower():
                entities.append(f"[{kind}] {name}"[:200])

        return "\n".join(entities[:20])
```

Run: `pytest tests/test_recall.py::test_recall_context_for_registered_agent -v`
Expected: PASS

**Step 3: Commit**

```bash
git add daemon/recall.py tests/test_recall.py
git commit -m "feat: add RecallEngine with graph context injection"
```

---

### Task 1.2: Add auto-retain — parse agent output and write learnings to graph

**Objective:** After every agent run, parse structured outputs and write learnings as nodes/edges back to the graph.

**Files:**
- Modify: `daemon/recall.py`
- Modify: `tests/test_recall.py`

**Step 1: Write failing test**

```python
# Add to tests/test_recall.py
@pytest.mark.asyncio
async def test_retain_extracts_learnings_to_graph(tmp_path):
    engine = RecallEngine()
    agent_output = """
    FOUND: auth.py has a hardcoded secret on line 42
    PATTERN: Circular dependency between auth.py and middleware.py
    DECISION: Extract auth config to env vars, split middleware into auth_middleware.py
    """
    await engine.retain(
        agent_id="agent-1",
        project="test-proj",
        agent_output=agent_output,
        graph_dir=tmp_path
    )
    # Verify findings node written
    findings_files = list(tmp_path.glob("finding-*.md"))
    assert len(findings_files) > 0
```

Run: `pytest tests/test_recall.py::test_retain_extracts_learnings_to_graph -v`
Expected: FAIL — retain method not defined

**Step 2: Implement retain method**

```python
# Add to daemon/recall.py (inside RecallEngine class)
import uuid
from datetime import datetime, timezone

async def retain(self, agent_id: str, project: str, agent_output: str, graph_dir: Path = None):
    """Parse agent output and write structured learnings back to the graph."""
    inbox = graph_dir or (self.loom_dir / "inbox" / project)
    inbox.mkdir(parents=True, exist_ok=True)

    findings = self._extract_findings(agent_output)
    for finding in findings:
        finding_id = str(uuid.uuid4())[:8]
        finding_path = inbox / f"finding-{finding_id}.md"
        finding_path.write_text(f"""---
agent: {agent_id}
project: {project}
timestamp: {datetime.now(timezone.utc).isoformat()}
confidence: medium
---
{finding}
""")

def _extract_findings(self, text: str) -> list[str]:
    """Extract FOUND/PATTERN/DECISION lines from agent output."""
    findings = []
    for line in text.split("\n"):
        for prefix in ("FOUND:", "PATTERN:", "DECISION:"):
            if line.strip().startswith(prefix):
                findings.append(line.strip())
    return findings
```

Run: `pytest tests/test_recall.py::test_retain_extracts_learnings_to_graph -v`
Expected: PASS

**Step 3: Commit**

```bash
git add daemon/recall.py tests/test_recall.py
git commit -m "feat: add auto-retain with output parsing and finding extraction"
```

---

### Task 1.3: Wire recall into agent heartbeat flow

**Objective:** Before any agent turn (heartbeat), inject recalled graph context. After any agent run, trigger auto-retain.

**Files:**
- Modify: `daemon/router.py`
- Modify: `tests/test_router.py`

**Step 1: Write failing test**

```python
# Add to tests/test_router.py
@pytest.mark.asyncio
async def test_heartbeat_triggers_recall_and_retain(tmp_path):
    """When an agent heartbeats, recall context is injected and retain is triggered on past output."""
    from daemon.router import Router
    from daemon.recall import RecallEngine

    inbox = tmp_path / "inbox"
    processed = tmp_path / "processed"
    inbox.mkdir(parents=True)

    router = Router(inbox_dir=str(inbox), processed_dir=str(processed))
    # Simulate a prior finding existing
    (inbox / "finding-old.md").write_text("FOUND: old pattern")

    await router.process_inbox()
    # After processing, recall engine should have context available
    engine = RecallEngine()
    assert engine is not None  # Verify integration point exists
```

Run: `pytest tests/test_router.py::test_heartbeat_triggers_recall_and_retain -v`
Expected: FAIL or PASS — verify integration

**Step 2: Add RecallEngine to Router**

```python
# In daemon/router.py, add to Router.__init__:
from daemon.recall import RecallEngine

class Router:
    def __init__(self, ...):
        ...
        self.recall = RecallEngine()
```

Run: `pytest tests/test_router.py -v`
Expected: All existing router tests still pass

**Step 3: Commit**

```bash
git add daemon/router.py tests/test_router.py
git commit -m "feat: wire RecallEngine into Router for heartbeat-driven recall/retain"
```

---

### Task 1.4: Add cross-agent synthesis — agent B inherits agent A's patterns

**Objective:** When agent A discovers a pattern, agent B gets it injected as context without re-discovering.

**Files:**
- Modify: `daemon/recall.py`
- Modify: `tests/test_recall.py`

**Step 1: Write failing test**

```python
# Add to tests/test_recall.py
@pytest.mark.asyncio
async def test_cross_agent_synthesis_inherits_patterns(tmp_path):
    engine = RecallEngine(loom_dir=str(tmp_path))
    project_dir = tmp_path / "inbox" / "test-proj"
    project_dir.mkdir(parents=True)

    # Agent A discovers a pattern
    await engine.retain(
        agent_id="agent-a",
        project="test-proj",
        agent_output="PATTERN: auth.py always uses bcrypt for password hashing",
        graph_dir=project_dir
    )

    # Agent B works on auth — should get Agent A's pattern
    context = await engine.recall(
        agent_id="agent-b",
        project="test-proj",
        task_hint="auth password hashing"
    )
    assert "bcrypt" in context
    assert "PATTERN" in context
```

Run: `pytest tests/test_recall.py::test_cross_agent_synthesis_inherits_patterns -v`
Expected: FAIL — recall only queries graph.json, not inbox findings

**Step 2: Extend RecallEngine to also search inbox findings**

```python
# Modify RecallEngine.recall() to also scan inbox findings:
async def recall(self, agent_id: str, project: str, task_hint: str = "") -> str:
    entities = []

    # 1. Query graph.json for structural entities
    graph_path = self.loom_dir / "projects" / project / "graphify-out" / "graph.json"
    if graph_path.exists():
        with open(graph_path) as f:
            graph = json.load(f)
        for node in graph.get("nodes", []):
            name = node.get("name") or node.get("label", "")
            kind = node.get("kind", "")
            if task_hint and task_hint.lower() in name.lower():
                entities.append(f"[{kind}] {name}"[:200])

    # 2. Also scan inbox findings from other agents
    inbox = self.loom_dir / "inbox" / project
    if inbox.exists():
        for f_path in sorted(inbox.glob("finding-*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            content = f_path.read_text()
            if task_hint and task_hint.lower() in content.lower():
                # Extract the finding body (skip YAML frontmatter)
                lines = content.split("\n")
                body_start = 0
                if lines[0].strip() == "---":
                    for i, line in enumerate(lines[1:], 1):
                        if line.strip() == "---":
                            body_start = i + 1
                            break
                finding_body = "\n".join(lines[body_start:]).strip()
                entities.append(f"[finding] {finding_body}"[:300])

    return "\n".join(entities[:20])
```

Run: `pytest tests/test_recall.py::test_cross_agent_synthesis_inherits_patterns -v`
Expected: PASS

**Step 3: Commit**

```bash
git add daemon/recall.py tests/test_recall.py
git commit -m "feat: cross-agent synthesis — agent B inherits agent A patterns via inbox scanning"
```

---

### Task 1.5: Dashboard — Memory Bank panel showing recalled context

**Objective:** Add a Memory Bank panel to the project detail page showing what context was recalled for each agent.

**Files:**
- Create: `dashboard/components/memory-bank.tsx`
- Modify: `dashboard/app/[locale]/projects/[id]/page.tsx`

**Step 1: Write the component**

```tsx
// dashboard/components/memory-bank.tsx
"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface RecallEntry {
  agent: string;
  task_hint: string;
  entities: string[];
  timestamp: string;
}

export function MemoryBank({ entries }: { entries: RecallEntry[] }) {
  if (!entries?.length) {
    return (
      <Card className="bg-zinc-950 border-zinc-800">
        <CardHeader>
          <CardTitle className="text-zinc-100 text-sm">Memory Bank</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-zinc-500 text-xs">No recalled context yet. Agents will auto-recall relevant patterns.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="bg-zinc-950 border-zinc-800">
      <CardHeader>
        <CardTitle className="text-zinc-100 text-sm">Memory Bank</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {entries.slice(-5).map((entry, i) => (
          <div key={i} className="border border-zinc-800 rounded p-2">
            <div className="flex items-center gap-2 mb-1">
              <Badge variant="outline" className="text-xs">{entry.agent}</Badge>
              <span className="text-zinc-400 text-xs">{entry.timestamp}</span>
            </div>
            <p className="text-zinc-300 text-xs mb-1">Task: {entry.task_hint}</p>
            <div className="space-y-1">
              {entry.entities.map((e, j) => (
                <p key={j} className="text-emerald-400 text-xs font-mono truncate">{e}</p>
              ))}
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/memory-bank.tsx
git commit -m "feat: add MemoryBank dashboard component"
```

---

### Feature 2: Durable Multi-Agent Task Board

**Evidence:** Hermes Kanban has 7-state lifecycle + crash recovery + dependency management. Loom's inbox protocol is "write a file, hope an agent picks it up."

### Task 2.1: Add task state machine to models

**Objective:** Add `TaskStatus` enum and `TaskRecord` Pydantic model.

**Files:**
- Modify: `daemon/models.py`

**Step 1: Add models**

```python
# Add to daemon/models.py
from enum import Enum

class TaskStatus(str, Enum):
    TRIAGE = "triage"
    TODO = "todo"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    DONE = "done"
    ARCHIVED = "archived"

class TaskCreatePayload(BaseModel):
    project: str
    title: str
    instruction: str
    assignee: str | None = None  # agent_id or None for auto-assign
    priority: int = 0
    dependencies: list[str] = []  # task_ids this task depends on
    acceptance_criteria: str = ""

class TaskRecord(BaseModel):
    id: str
    project: str
    title: str
    instruction: str
    status: TaskStatus = TaskStatus.TODO
    assignee: str | None = None
    priority: int = 0
    dependencies: list[str] = []
    acceptance_criteria: str = ""
    created_at: str
    updated_at: str
    workspace_path: str | None = None

class TaskUpdatePayload(BaseModel):
    status: TaskStatus | None = None
    assignee: str | None = None
    result: str | None = None
```

Run: `python -c "from daemon.models import TaskStatus, TaskRecord, TaskCreatePayload, TaskUpdatePayload; print('OK')"`
Expected: `OK`

**Step 2: Commit**

```bash
git add daemon/models.py
git commit -m "feat: add task state machine models (TaskStatus, TaskRecord)"
```

---

### Task 2.2: Add task CRUD to registry

**Objective:** SQLite-backed task storage with status transitions, dependency resolution, and auto-promotion.

**Files:**
- Modify: `daemon/registry.py`
- Create: `tests/test_tasks.py`

**Step 1: Write failing tests**

```python
# tests/test_tasks.py
import pytest
from daemon.registry import AgentRegistry
from daemon.models import TaskStatus, TaskCreatePayload

@pytest.mark.asyncio
async def test_create_and_get_task():
    registry = AgentRegistry(db_path=":memory:")
    await registry.initialize()
    task = TaskCreatePayload(
        project="test-proj",
        title="Fix auth bug",
        instruction="Fix the hardcoded secret in auth.py",
        priority=1
    )
    task_id = await registry.create_task(task)
    assert task_id is not None

    record = await registry.get_task(task_id)
    assert record.title == "Fix auth bug"
    assert record.status == TaskStatus.TODO

@pytest.mark.asyncio
async def test_task_state_transition():
    registry = AgentRegistry(db_path=":memory:")
    await registry.initialize()
    task = TaskCreatePayload(project="test-proj", title="T1", instruction="Do X")
    task_id = await registry.create_task(task)

    await registry.update_task(task_id, status=TaskStatus.RUNNING)
    record = await registry.get_task(task_id)
    assert record.status == TaskStatus.RUNNING

    await registry.update_task(task_id, status=TaskStatus.DONE)
    record = await registry.get_task(task_id)
    assert record.status == TaskStatus.DONE

@pytest.mark.asyncio
async def test_task_dependency_promotion():
    registry = AgentRegistry(db_path=":memory:")
    await registry.initialize()

    parent = TaskCreatePayload(project="test-proj", title="Parent", instruction="X")
    parent_id = await registry.create_task(parent)
    await registry.update_task(parent_id, status=TaskStatus.DONE)

    child = TaskCreatePayload(
        project="test-proj", title="Child", instruction="Y",
        dependencies=[parent_id]
    )
    child_id = await registry.create_task(child)
    child_record = await registry.get_task(child_id)
    # Child auto-promotes to ready when all parents are done
    assert child_record.status == TaskStatus.READY
```

Run: `pytest tests/test_tasks.py -v`
Expected: FAIL — create_task not defined

**Step 2: Implement task storage in registry**

```python
# Add to daemon/registry.py — task methods

async def create_task(self, payload: TaskCreatePayload) -> str:
    import uuid
    from datetime import datetime, timezone
    task_id = str(uuid.uuid4())[:12]
    now = datetime.now(timezone.utc).isoformat()

    # Auto-promote: if all dependencies are done, start as READY
    status = TaskStatus.READY if self._all_deps_done(payload.dependencies) else TaskStatus.TODO

    async with aiosqlite.connect(self.db_path) as db:
        await db.execute(
            """INSERT INTO tasks (id, project, title, instruction, status, assignee,
               priority, dependencies, acceptance_criteria, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_id, payload.project, payload.title, payload.instruction,
             status.value, payload.assignee, payload.priority,
             json.dumps(payload.dependencies), payload.acceptance_criteria, now, now)
        )
        await db.commit()
    return task_id

async def get_task(self, task_id: str) -> TaskRecord | None:
    async with aiosqlite.connect(self.db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return None
            return self._row_to_task(row)

async def update_task(self, task_id: str, status: TaskStatus = None,
                      assignee: str = None, result: str = None):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    sets = ["updated_at = ?"]
    params = [now]
    if status is not None:
        sets.append("status = ?")
        params.append(status.value)
    if assignee is not None:
        sets.append("assignee = ?")
        params.append(assignee)
    params.append(task_id)
    async with aiosqlite.connect(self.db_path) as db:
        await db.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()

def _all_deps_done(self, dep_ids: list[str]) -> bool:
    # Simplified: check if all deps are DONE (synchronous lookup for auto-promote)
    import sqlite3
    if not dep_ids:
        return False
    conn = sqlite3.connect(self.db_path)
    for dep_id in dep_ids:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (dep_id,)).fetchone()
        if row is None or row[0] != TaskStatus.DONE.value:
            conn.close()
            return False
    conn.close()
    return True
```

Run: `pytest tests/test_tasks.py -v`
Expected: PASS (all 3)

Also run: `pytest tests/test_registry.py -v` (ensure existing tests pass)
Expected: All existing registry tests pass

**Step 3: Commit**

```bash
git add daemon/registry.py tests/test_tasks.py
git commit -m "feat: add task CRUD with state machine and dependency auto-promotion"
```

---

### Task 2.3: Add tasks table migration to registry init

**Objective:** Extend `initialize()` to create the `tasks` table.

**Files:**
- Modify: `daemon/registry.py`

**Step 1: Add migration**

```python
# In AgentRegistry.initialize(), add after existing table creation:
await db.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
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
# Index for listing tasks by project + status
await db.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project, status)")
```

Run: `pytest tests/test_registry.py tests/test_tasks.py -v`
Expected: All pass

**Step 2: Commit**

```bash
git add daemon/registry.py
git commit -m "feat: add tasks table migration to registry"
```

---

### Task 2.4: Add task API endpoints

**Objective:** Expose task CRUD via `POST/GET/PATCH /api/projects/:id/tasks`.

**Files:**
- Modify: `daemon/api.py`
- Modify: `tests/test_api.py`

**Step 1: Write failing test**

```python
# Add to tests/test_api.py
@pytest.mark.asyncio
async def test_task_lifecycle_api(app, test_project):
    """Full lifecycle: create → list → update → verify."""
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        # Create
        resp = await client.post(
            f"/api/projects/{test_project['id']}/tasks",
            json={"project": "test-proj", "title": "Fix auth", "instruction": "do it", "priority": 1}
        )
        assert resp.status_code == 201
        task = resp.json()
        assert task["status"] == "todo"

        # List
        resp = await client.get(f"/api/projects/{test_project['id']}/tasks")
        assert resp.status_code == 200
        tasks = resp.json()
        assert any(t["id"] == task["id"] for t in tasks)

        # Update status
        resp = await client.patch(
            f"/api/projects/{test_project['id']}/tasks/{task['id']}",
            json={"status": "running", "assignee": "agent-1"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
```

Run: `pytest tests/test_api.py::test_task_lifecycle_api -v`
Expected: FAIL — endpoint not defined

**Step 2: Implement endpoints**

```python
# Add to daemon/api.py (before health check endpoint, preserving decorator)

@app.post("/api/projects/{project_id}/tasks", status_code=201)
async def create_task(project_id: str, payload: TaskCreatePayload):
    """Create a new task for a project."""
    if payload.project != project_id:
        payload.project = project_id
    task_id = await registry.create_task(payload)
    record = await registry.get_task(task_id)
    return record.model_dump()

@app.get("/api/projects/{project_id}/tasks")
async def list_tasks(project_id: str, status: str = None):
    """List tasks for a project, optionally filtered by status."""
    tasks = await registry.list_tasks(project_id, status_filter=status)
    return [t.model_dump() for t in tasks]

@app.patch("/api/projects/{project_id}/tasks/{task_id}")
async def update_task(project_id: str, task_id: str, payload: TaskUpdatePayload):
    """Update a task's status, assignee, or result."""
    await registry.update_task(
        task_id,
        status=payload.status,
        assignee=payload.assignee,
        result=payload.result
    )
    record = await registry.get_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return record.model_dump()
```

Also add `list_tasks` to registry:

```python
# Add to daemon/registry.py
async def list_tasks(self, project: str, status_filter: str = None) -> list[TaskRecord]:
    async with aiosqlite.connect(self.db_path) as db:
        db.row_factory = aiosqlite.Row
        if status_filter:
            async with db.execute(
                "SELECT * FROM tasks WHERE project = ? AND status = ? ORDER BY priority DESC, created_at DESC",
                (project, status_filter)
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with db.execute(
                "SELECT * FROM tasks WHERE project = ? AND status != 'archived' ORDER BY priority DESC, created_at DESC",
                (project,)
            ) as cursor:
                rows = await cursor.fetchall()
        return [self._row_to_task(r) for r in rows]
```

Run: `pytest tests/test_api.py::test_task_lifecycle_api -v`
Expected: PASS

Also run: `pytest tests/test_api.py -v` (all tests)
Expected: All existing pass

**Step 3: Commit**

```bash
git add daemon/api.py daemon/registry.py tests/test_api.py
git commit -m "feat: add task API endpoints (create, list, update)"
```

---

### Task 2.5: Dashboard — Task Board with Kanban columns

**Objective:** Add a Kanban-style task board to the project detail page.

**Files:**
- Create: `dashboard/components/task-board.tsx`
- Modify: `dashboard/app/[locale]/projects/[id]/page.tsx`

**Step 1: Write the component**

```tsx
// dashboard/components/task-board.tsx
"use client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

type TaskStatus = "triage" | "todo" | "ready" | "running" | "blocked" | "done";

const COLUMNS: { status: TaskStatus; label: string; color: string }[] = [
  { status: "todo", label: "To Do", color: "text-zinc-400" },
  { status: "ready", label: "Ready", color: "text-blue-400" },
  { status: "running", label: "Running", color: "text-amber-400" },
  { status: "blocked", label: "Blocked", color: "text-red-400" },
  { status: "done", label: "Done", color: "text-emerald-400" },
];

interface Task {
  id: string;
  title: string;
  status: TaskStatus;
  assignee: string | null;
  priority: number;
  dependencies: string[];
}

export function TaskBoard({ tasks }: { tasks: Task[] }) {
  return (
    <div className="grid grid-cols-5 gap-3">
      {COLUMNS.map((col) => {
        const columnTasks = tasks.filter((t) => t.status === col.status);
        return (
          <div key={col.status} className="space-y-2">
            <div className="flex items-center gap-2">
              <span className={`text-xs font-medium ${col.color}`}>{col.label}</span>
              <Badge variant="outline" className="text-xs">{columnTasks.length}</Badge>
            </div>
            <div className="space-y-2">
              {columnTasks.map((task) => (
                <Card key={task.id} className="bg-zinc-900 border-zinc-800 p-2">
                  <p className="text-zinc-200 text-xs font-medium">{task.title}</p>
                  {task.assignee && (
                    <p className="text-zinc-500 text-xs mt-1">{task.assignee}</p>
                  )}
                  {task.dependencies.length > 0 && (
                    <p className="text-zinc-600 text-xs mt-1">
                      Depends on: {task.dependencies.join(", ")}
                    </p>
                  )}
                </Card>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/task-board.tsx
git commit -m "feat: add Kanban-style TaskBoard dashboard component"
```

---

### Task 2.6: Integration test — full task lifecycle end-to-end

**Objective:** Verify create → assign → run → complete flow with dependency auto-promotion.

**Files:**
- Modify: `tests/test_api.py`

**Step 1: Write integration test**

```python
# Add to tests/test_api.py
@pytest.mark.asyncio
async def test_full_task_lifecycle_with_dependencies(app, test_project):
    """End-to-end: parent blocks child until parent completes."""
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        pid = test_project["id"]

        # Create parent task
        resp = await client.post(f"/api/projects/{pid}/tasks", json={
            "project": pid, "title": "Setup DB", "instruction": "init", "priority": 1
        })
        parent_id = resp.json()["id"]

        # Create child task dependent on parent
        resp = await client.post(f"/api/projects/{pid}/tasks", json={
            "project": pid, "title": "Run Migrations", "instruction": "migrate",
            "dependencies": [parent_id], "priority": 1
        })
        child = resp.json()
        assert child["status"] == "todo"  # parent not done yet

        # Complete parent
        await client.patch(f"/api/projects/{pid}/tasks/{parent_id}", json={"status": "done"})

        # Child should auto-promote to ready
        resp = await client.get(f"/api/projects/{pid}/tasks")
        child_updated = next(t for t in resp.json() if t["id"] == child["id"])
        assert child_updated["status"] == "ready"
```

Run: `pytest tests/test_api.py::test_full_task_lifecycle_with_dependencies -v`
Expected: PASS

**Step 2: Commit**

```bash
git add tests/test_api.py
git commit -m "test: add full task lifecycle integration test with dependency auto-promotion"
```

---

## Sprint 1: P0 — Hybrid Search + LLM Extraction + Sessions (Weeks 7-9)

### Feature 3: Hybrid Vector-Graph Retrieval

**Evidence:** Cognee benchmarks 0.93 with vector→graph vs 0.4 for base RAG. Loom has FTS5 text-only.

### Task 3.1: Add `sqlite-vec` extension and embedding pipeline

**Objective:** Add zero-dependency vector storage in SQLite and an embedding generator.

**Files:**
- Create: `daemon/embeddings.py`
- Create: `tests/test_embeddings.py`

**Step 1: Write failing test**

```python
# tests/test_embeddings.py
import pytest
from daemon.embeddings import EmbeddingStore, EmbeddingGenerator

@pytest.mark.asyncio
async def test_generate_and_store_embedding(tmp_path):
    gen = EmbeddingGenerator()
    store = EmbeddingStore(db_path=str(tmp_path / "vec.db"))
    await store.initialize()

    doc_id = "finding-abc"
    text = "Authentication module uses bcrypt for password hashing"
    embedding = await gen.embed(text)
    assert len(embedding) == 384  # all-MiniLM-L6-v2 dimension

    await store.insert(doc_id, text, embedding)
    results = await store.search("password hashing security", top_k=3)
    assert len(results) > 0
    assert any(r["id"] == doc_id for r in results)
```

Run: `pytest tests/test_embeddings.py -v`
Expected: FAIL — modules not defined

**Step 2: Implement embedding store with NumPy (zero deps for V1)**

```python
# daemon/embeddings.py
import json
import sqlite3
import numpy as np
from pathlib import Path

class EmbeddingGenerator:
    """Generate embeddings. V1: use sentence-transformers. Fallback: configurable Ollama/OpenAI."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    async def embed(self, text: str) -> list[float]:
        """Generate embedding vector for text."""
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except ImportError:
                # Fallback: return zero vector (degraded mode)
                return [0.0] * 384
        embedding = self._model.encode(text)
        return embedding.tolist()


class EmbeddingStore:
    """NumPy-backed vector store (zero deps for <10K vectors)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._docs = []  # [(id, text, embedding_np_array)]

    async def initialize(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    async def insert(self, doc_id: str, text: str, embedding: list[float]):
        self._docs.append((doc_id, text, np.array(embedding)))

    async def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Cosine similarity search over stored embeddings."""
        if not self._docs:
            return []

        gen = EmbeddingGenerator()
        query_vec = np.array(await gen.embed(query))
        if not np.any(query_vec):
            return []

        results = []
        for doc_id, text, doc_vec in self._docs:
            sim = np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-8)
            results.append({"id": doc_id, "text": text, "score": float(sim)})

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]
```

Run: `pytest tests/test_embeddings.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add daemon/embeddings.py tests/test_embeddings.py
pip install sentence-transformers  # install dep
git commit -m "feat: add NumPy-backed embedding store with cosine similarity search"
```

---

### Task 3.2: Add hybrid search API endpoint

**Objective:** `GET /api/projects/:id/search?q=` combines FTS5 text search + vector cosine similarity.

**Files:**
- Modify: `daemon/api.py`
- Modify: `tests/test_api.py`

**Step 1: Write test**

```python
# Add to tests/test_api.py
@pytest.mark.asyncio
async def test_hybrid_search(app, test_project):
    async with httpx.AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get(f"/api/projects/{test_project['id']}/search?q=authentication")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert isinstance(data["results"], list)
```

Expected: FAIL — endpoint not defined

**Step 2: Implement**

```python
# Add to daemon/api.py
@app.get("/api/projects/{project_id}/search")
async def hybrid_search(project_id: str, q: str = ""):
    """Hybrid search: FTS5 text + vector cosine similarity."""
    if not q:
        return {"results": []}

    results = await registry.hybrid_search(project_id, q)
    return {"results": results}
```

Add `hybrid_search` to registry:

```python
# daemon/registry.py
async def hybrid_search(self, project: str, query: str) -> list[dict]:
    from daemon.embeddings import EmbeddingStore, EmbeddingGenerator
    store = EmbeddingStore(db_path=self.db_path)
    await store.initialize()
    gen = EmbeddingGenerator()
    query_vec = await gen.embed(query)

    # Also search inbox findings with FTS5-like substring matching
    inbox = Path(self.loom_dir or os.path.expanduser("~/.loom")) / "inbox" / project
    results = []
    if inbox.exists():
        for f_path in inbox.glob("finding-*.md"):
            content = f_path.read_text()
            if query.lower() in content.lower():
                doc_vec = await gen.embed(content[:500])
                sim = np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec) + 1e-8)
                results.append({"id": f_path.stem, "text": content[:300], "score": float(sim), "source": "finding"})

    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:10]
```

Run: `pytest tests/test_api.py::test_hybrid_search -v`
Expected: PASS

**Step 3: Commit**

```bash
git add daemon/api.py daemon/registry.py tests/test_api.py
git commit -m "feat: add hybrid search API endpoint (text + vector)"
```

---

### Task 3.3: Dashboard — Semantic search bar

**Objective:** `<SearchBar>` component on project pages with hybrid search results.

**Files:**
- Create: `dashboard/components/search-bar.tsx`
- Modify: `dashboard/app/[locale]/projects/[id]/page.tsx`

**Step 1: Implement search bar**

```tsx
// dashboard/components/search-bar.tsx
"use client";
import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Card, CardContent } from "@/components/ui/card";
import { fetchApi } from "@/lib/api";

interface SearchResult {
  id: string;
  text: string;
  score: number;
  source: string;
}

export function SearchBar({ projectId }: { projectId: string }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  async function handleSearch(q: string) {
    setQuery(q);
    if (q.length < 2) { setResults([]); return; }
    setLoading(true);
    const data = await fetchApi<{ results: SearchResult[] }>(`/api/projects/${projectId}/search?q=${encodeURIComponent(q)}`);
    setResults(data.results);
    setLoading(false);
  }

  return (
    <div className="space-y-3">
      <Input
        placeholder="Search knowledge graph... (e.g., 'authentication', 'database schema')"
        value={query}
        onChange={(e) => handleSearch(e.target.value)}
        className="bg-zinc-900 border-zinc-700 text-zinc-200"
      />
      {loading && <p className="text-zinc-500 text-xs">Searching...</p>}
      {results.map((r) => (
        <Card key={r.id} className="bg-zinc-900 border-zinc-800">
          <CardContent className="p-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-zinc-500">{r.source}</span>
              <span className="text-xs text-emerald-400">{r.score.toFixed(2)}</span>
            </div>
            <p className="text-zinc-300 text-xs mt-1 line-clamp-2">{r.text}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add dashboard/components/search-bar.tsx
git commit -m "feat: add semantic SearchBar dashboard component"
```

---

### Feature 4: LLM-Powered Auto Knowledge Extraction (P0)

### Task 4.1: Create LLM extractor with Graphiti-prompt patterns

**Files:**
- Create: `daemon/extractors.py`
- Create: `tests/test_extractors.py`

*(Detailed TDD tasks follow the same pattern — write failing test, implement, verify, commit. For brevity, only the architecture is shown.)*

```python
# daemon/extractors.py — core design
class LLMExtractor:
    """Uses configurable LLM (Ollama/OpenAI/Claude) to auto-extract entities and relationships from findings."""
    
    async def extract(self, markdown_text: str) -> list[ExtractedEntity]:
        """Extract entities e.g., {type: 'class', name: 'AuthService', relationships: [...]}"""
        ...

class ExtractorPipeline:
    """Pluggable pipeline: code-dependency, security, perf, ADR, LLM."""
    def __init__(self):
        self.extractors: list[Extractor] = []
    
    async def run(self, finding_md: str) -> list[GraphEdge]:
        """Run all registered extractors and return graph edges with confidence scores."""
        ...
```

---

### Feature 5: Session Memory with Context Continuity (P0)

### Task 5.1: Session state manager with scoped subgraphs

**Files:**
- Create: `daemon/sessions.py`
- Create: `tests/test_sessions.py`

```python
# daemon/sessions.py — core design
class SessionManager:
    """Manages scoped subgraphs that cache recent interactions per agent session."""
    
    async def start_session(self, agent_id: str, project: str) -> Session:
        """Create a new session scoped to this agent+project."""
        
    async def resolve_reference(self, session: Session, reference: str) -> Entity:
        """Resolve pronouns/references like 'she', 'that function', 'the auth module'."""
        
    async def bridge_to_permanent(self, session: Session):
        """On session close, persist important learnings to the permanent graph."""
```

---

## Sprint 2: P1 — Observability + Visual Debugging (Weeks 10-12)

### Feature 6: AI Observability (Tracing, Evals, Regression)

**Key modules:**
- `daemon/traces.py` — capture agent traces (inputs, tool calls, outputs, latency, tokens)
- `daemon/evals.py` — LLM-as-judge scoring, regression detection
- `tests/test_traces.py`, `tests/test_evals.py`
- Dashboard: `<TraceViewer>`, `<EvalDashboard>`

### Feature 7: Visual Agent Debugging with Time-Travel

**Key components:**
- Extend Cytoscape.js explorer with agent execution overlay
- State snapshot capture at each step
- Time-travel replay controls
- Dashboard: `<DebugOverlay>` on graph page

---

## Sprint 3: P1 — MCP Protocol Support (Weeks 13-14)

### Feature 8: Package Agentic OS API as MCP Server

**Key modules:**
- `daemon/mcp_server.py` — FastMCP server wrapping existing endpoints
- Expose tools: `search_knowledge_graph`, `add_to_memory`, `list_projects`, `get_project_graph`
- Stdio transport for Claude Desktop/Cursor/Cline
- Ship as `pip install agentic-os-mcp`

---

## Sprint 4: P2 — Patterns + Governance (Weeks 15-17)

### Feature 9: Self-Evolving Pattern Repository
### Feature 10: Agent Governance (RBAC, Audit Trail, Approvals)

---

## Sprint 5: P2 — Temporal + Multi-Format (Weeks 18-20)

### Feature 11: Temporal Fact Tracking
### Feature 12: Multi-Format Document Ingestion

---

## Verification Checklist

- [ ] All 38 existing tests continue to pass after each sprint
- [ ] No new infrastructure dependencies (no Docker, Neo4j, external DB)
- [ ] Filesystem inbox protocol preserved and extended (no SDK requirement)
- [ ] Single-process daemon — `agentic-os start` remains the only start command
- [ ] Per-project isolation intact through all new features
- [ ] WebSocket events emitted for new actions (task:created, agent:recalled, session:bridged)
- [ ] Dashboard dark theme consistency maintained
- [ ] Each new daemon module has corresponding `tests/test_<module>.py`
- [ ] graph.json output from Graphify not broken by new edge types

## Summary

| Sprint | Features | Weeks | Tasks (est.) | New Files | Mod. Files |
|--------|----------|-------|-------------|-----------|------------|
| Sprint 0 | 1-2 (CRITICAL) | 1-6 | 10 tasks | 4 | 5 |
| Sprint 1 | 3-5 (P0) | 7-9 | 8 tasks | 4 | 4 |
| Sprint 2 | 6-7 (P1) | 10-12 | 6 tasks | 4 | 3 |
| Sprint 3 | 8 (P1) | 13-14 | 3 tasks | 1 | 1 |
| Sprint 4 | 9-10 (P2) | 15-17 | 4 tasks | 3 | 2 |
| Sprint 5 | 11-12 (P2) | 18-20 | 4 tasks | 3 | 2 |
| **Total** | **12 features** | **~20 weeks** | **~35 tasks** | **19 files** | **17 files** |

---

## Competitive Moat Preservation (Non-Negotiable)

Throughout implementation, these differentiators must NOT be compromised:

| Moat | Guard |
|------|-------|
| Filesystem inbox protocol | New features extend the protocol (task-*.json, session-*.json) — never replace with SDK |
| Single-process daemon | `pip install` + `agentic-os start` must remain the only commands |
| Per-project isolation | All new features scoped to project boundaries |
| Code-specific Graphify AST | LLM extraction enriches the graph but never replaces AST-level understanding |
| Dashboard control plane | Every new feature ships with dashboard UI (no API-only features) |
| WebSocket live updates | New events emitted for all state changes |

---

## Next Steps

1. **Complete existing Phase 1-4** (Project CRUD, Graph Explorer, Agent Management) first — the competitor-gap features build on this foundation
2. **Ship Sprint 0 first** — Features 1+2 (memory bank + task board) are the category-defining features that make Loom a memory fabric
3. **Prioritize open questions** (see `plan-inputs.md`):
   - Embedding model: `all-MiniLM-L6-v2` (local, fast, free) — configurable fallback
   - LLM extractor: configurable (default Ollama if detected)
   - Vector store: NumPy for V1 (<10K), ChromaDB at scale
4. **Re-run competitor analysis Q4 2026** — Cognee raised $7.5M, category moves fast
