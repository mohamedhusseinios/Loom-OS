# Agentic OS — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build the Agentic OS daemon (Python/FastAPI) and dashboard (Next.js) that unifies AI coding agents through a shared Graphify-powered knowledge graph.

**Architecture:** Single Python daemon with 4 internal components (Watcher, Router, Graph Engine, Agent Registry) exposing REST + WebSocket API. Separate Next.js dashboard consuming that API. Agents communicate via filesystem hooks (`~/.agentic-os/inbox/`).

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, watchdog, Graphify (graphifyy), SQLite (aiosqlite), Pydantic. Next.js 15, Shadcn UI, Tailwind, TypeScript.

---

## Phase 1: Project Scaffold

### Task 1: Initialize Python daemon project

**Objective:** Set up the Python package with pyproject.toml and all dependencies.

**Files:**
- Create: `daemon/__init__.py`
- Create: `pyproject.toml`
- Create: `.gitignore`

**Step 1: Write pyproject.toml**

```toml
[project]
name = "agentic-os"
version = "0.1.0"
description = "Agentic OS — unified agent memory fabric"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",
    "watchdog>=5.0.0",
    "graphifyy>=0.8.0",
    "pydantic>=2.0",
    "aiosqlite>=0.20.0",
]

[project.scripts]
agentic-os = "daemon.main:main"

[build-system]
requires = ["setuptools>=75.0"]
build-backend = "setuptools.build_meta"
```

**Step 2: Write .gitignore**

```
__pycache__/
*.pyc
.venv/
node_modules/
.next/
graphify-out/
*.db
.env
dist/
```

**Step 3: Create empty __init__.py**

```python
"""Agentic OS — unified agent memory fabric."""
```

**Step 4: Install dependencies and verify**

```bash
cd /Users/mohamedabdulrahman/mohamed-hussien/my-projects/agentic-os
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -c "import daemon; print('daemon package OK')"
python -c "import fastapi, watchdog, graphify, pydantic, aiosqlite; print('all deps OK')"
```

**Step 5: Commit**

```bash
git add pyproject.toml .gitignore daemon/__init__.py
git commit -m "chore: initialize Python daemon project"
```

---

### Task 2: Initialize Next.js dashboard

**Objective:** Scaffold the Next.js app with Shadcn UI and Tailwind.

**Files:**
- Create: `dashboard/` (via create-next-app)

**Step 1: Scaffold Next.js**

```bash
cd /Users/mohamedabdulrahman/mohamed-hussien/my-projects/agentic-os
npx create-next-app@latest dashboard --typescript --tailwind --eslint --app --src-dir=false --import-alias="@/*" --use-npm --no-turbopack
```

**Step 2: Install Shadcn UI**

```bash
cd dashboard
npx shadcn@latest init -d
npx shadcn@latest add card badge separator scroll-area input button sidebar
```

**Step 3: Install lucide-react icons**

```bash
cd dashboard && npm install lucide-react
```

**Step 4: Add dashboard/.gitignore entry to root .gitignore**

Already covered by `node_modules/` and `.next/` in Task 1's .gitignore.

**Step 5: Verify**

```bash
cd dashboard && npm run build
```

Expected: successful build with no errors.

**Step 6: Commit**

```bash
git add dashboard/
git commit -m "chore: scaffold Next.js dashboard with Shadcn UI"
```

---

## Phase 2: Daemon — Data Models

### Task 3: Create Pydantic models

**Objective:** Define all data schemas for the daemon: agents, projects, inbox files, API responses.

**Files:**
- Create: `daemon/models.py`

**Step 1: Write models.py**

```python
"""Pydantic models for the Agentic OS daemon."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class AgentStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    WORKING = "working"


class FindingType(str, Enum):
    CODE_ANALYSIS = "code-analysis"
    ARCHITECTURE_DECISION = "architecture-decision"
    BUG_REPORT = "bug-report"
    GENERAL = "general"


# --- Inbox File Schemas ---

class RegisterPayload(BaseModel):
    agent: str
    version: str
    project: str
    project_path: str
    capabilities: list[str] = Field(default_factory=list)


class HeartbeatPayload(BaseModel):
    agent: str
    project: str
    status: str = ""
    timestamp: datetime


class FindingFrontmatter(BaseModel):
    agent: str
    project: str
    type: FindingType = FindingType.GENERAL
    files: list[str] = Field(default_factory=list)
    timestamp: Optional[datetime] = None


# --- Registry Models ---

class AgentInfo(BaseModel):
    agent_id: str
    agent_name: str
    version: str
    project: str
    capabilities: list[str]
    status: AgentStatus = AgentStatus.ONLINE
    last_heartbeat: Optional[datetime] = None
    registered_at: datetime = Field(default_factory=datetime.utcnow)


class ProjectInfo(BaseModel):
    project_id: str
    project_name: str
    project_path: str
    node_count: int = 0
    edge_count: int = 0
    community_count: int = 0
    last_graph_update: Optional[datetime] = None
    active_agents: int = 0
    total_findings: int = 0


# --- API Response Schemas ---

class GraphStats(BaseModel):
    nodes: int
    edges: int
    communities: int
    top_communities: list[dict] = Field(default_factory=list)
    god_nodes: list[dict] = Field(default_factory=list)
    last_updated: Optional[datetime] = None


class ProjectSummary(BaseModel):
    project: ProjectInfo
    graph: Optional[GraphStats] = None
    agents: list[AgentInfo] = Field(default_factory=list)


class ActivityEvent(BaseModel):
    timestamp: datetime
    event_type: str
    project: str
    agent: Optional[str] = None
    details: dict = Field(default_factory=dict)


class QueryResult(BaseModel):
    question: str
    results: list[dict]
    communities: list[str] = Field(default_factory=list)


class BuildResult(BaseModel):
    project: str
    status: str  # "started" | "completed" | "failed"
    nodes: int = 0
    edges: int = 0
    error: Optional[str] = None


# --- WebSocket Events ---

class WsEvent(BaseModel):
    event: str
    project: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
```

**Step 2: Verify models import**

```bash
cd /Users/mohamedabdulrahman/mohamed-hussien/my-projects/agentic-os
source .venv/bin/activate
python -c "from daemon.models import RegisterPayload, HeartbeatPayload, AgentInfo, ProjectInfo, GraphStats; print('all models OK')"
```

**Step 3: Commit**

```bash
git add daemon/models.py
git commit -m "feat: add Pydantic data models for daemon"
```

---

### Task 4: Implement Agent Registry (SQLite)

**Objective:** SQLite-backed CRUD for agents and projects. Async with aiosqlite.

**Files:**
- Create: `daemon/registry.py`
- Create: `tests/test_registry.py`

**Step 1: Write failing test**

```python
"""Tests for the Agent Registry."""
import pytest
import asyncio
from pathlib import Path
from daemon.registry import AgentRegistry
from daemon.models import AgentInfo, ProjectInfo, AgentStatus


@pytest.fixture
async def registry(tmp_path):
    db_path = tmp_path / "test.db"
    reg = AgentRegistry(str(db_path))
    await reg.initialize()
    yield reg
    await reg.close()


@pytest.mark.asyncio
async def test_register_agent(registry):
    agent = AgentInfo(
        agent_id="claude-code-noor",
        agent_name="claude-code",
        version="2.1.190",
        project="noor",
        capabilities=["code-analysis", "refactoring"],
    )
    await registry.upsert_agent(agent)
    result = await registry.get_agent("claude-code-noor")
    assert result is not None
    assert result.agent_name == "claude-code"
    assert result.project == "noor"
```

**Step 2: Run test to verify failure**

```bash
pytest tests/test_registry.py::test_register_agent -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.registry'`

**Step 3: Write minimal registry.py**

```python
"""SQLite-backed agent and project registry."""

import aiosqlite
from typing import Optional
from daemon.models import AgentInfo, ProjectInfo, AgentStatus


class AgentRegistry:
    def __init__(self, db_path: str = "~/.agentic-os/state.db"):
        self.db_path = db_path
        self.db: Optional[aiosqlite.Connection] = None

    async def initialize(self):
        self.db = await aiosqlite.connect(self.db_path)
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
                str(agent.capabilities),
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
        return AgentInfo(
            agent_id=row["agent_id"],
            agent_name=row["agent_name"],
            version=row["version"],
            project=row["project"],
            capabilities=eval(row["capabilities"]),
            status=AgentStatus(row["status"]),
            last_heartbeat=row["last_heartbeat"],
            registered_at=row["registered_at"],
        )
```

**Step 4: Run test to verify pass**

```bash
pytest tests/test_registry.py::test_register_agent -v
```
Expected: PASS

**Step 5: Commit**

```bash
mkdir -p tests
git add daemon/registry.py tests/test_registry.py
git commit -m "feat: implement Agent Registry with SQLite backend"
```

---

## Phase 3: Daemon — Core Engine

### Task 5: Implement Graph Engine (Graphify wrapper)

**Objective:** Async wrapper around Graphify. Build, update, query, stats. CPU-bound work in thread pool.

**Files:**
- Create: `daemon/graph_engine.py`
- Create: `tests/test_graph_engine.py`

**Step 1: Write failing test**

```python
"""Tests for the Graph Engine."""
import pytest
from pathlib import Path
from daemon.graph_engine import GraphEngine


@pytest.mark.asyncio
async def test_get_stats_no_graph(tmp_path):
    """Stats should return zeros when no graph exists."""
    engine = GraphEngine()
    project_path = str(tmp_path)
    stats = await engine.get_stats(project_path)
    assert stats.nodes == 0
    assert stats.edges == 0
    assert stats.communities == 0
```

**Step 2: Run to verify failure**

```bash
pytest tests/test_graph_engine.py::test_get_stats_no_graph -v
```
Expected: FAIL

**Step 3: Write graph_engine.py**

```python
"""Graphify wrapper for the Agentic OS daemon."""

import asyncio
import json
from pathlib import Path
from typing import Optional
from daemon.models import BuildResult, GraphStats, QueryResult


class GraphEngine:
    """Async wrapper around Graphify for build/update/query/stats."""

    def __init__(self):
        self._graphify = None
        try:
            import graphify
            self._graphify = graphify
        except ImportError:
            pass

    @property
    def available(self) -> bool:
        return self._graphify is not None

    async def build_project(self, project_path: str) -> BuildResult:
        """Run full Graphify build on a project."""
        project_name = Path(project_path).name
        if not self.available:
            return BuildResult(
                project=project_name,
                status="failed",
                error="Graphify not installed",
            )
        try:
            # Graphify build is CPU-bound — run in thread
            await asyncio.to_thread(
                self._run_graphify_build, project_path
            )
            stats = await self.get_stats(project_path)
            return BuildResult(
                project=project_name,
                status="completed",
                nodes=stats.nodes,
                edges=stats.edges,
            )
        except Exception as e:
            return BuildResult(
                project=project_name,
                status="failed",
                error=str(e),
            )

    def _run_graphify_build(self, project_path: str):
        """Run graphify CLI build (blocking)."""
        import subprocess
        subprocess.run(
            ["graphify", project_path],
            capture_output=True,
            timeout=300,
            check=True,
        )

    async def update_project(self, project_path: str, files: list[str]) -> BuildResult:
        """Incremental update for changed files."""
        project_name = Path(project_path).name
        if not self.available:
            return BuildResult(
                project=project_name,
                status="failed",
                error="Graphify not installed",
            )
        try:
            await asyncio.to_thread(
                self._run_graphify_update, project_path
            )
            stats = await self.get_stats(project_path)
            return BuildResult(
                project=project_name,
                status="completed",
                nodes=stats.nodes,
                edges=stats.edges,
            )
        except Exception as e:
            return BuildResult(
                project=project_name,
                status="failed",
                error=str(e),
            )

    def _run_graphify_update(self, project_path: str):
        """Run graphify --update (blocking)."""
        import subprocess
        subprocess.run(
            ["graphify", project_path, "--update"],
            capture_output=True,
            timeout=300,
            check=True,
        )

    async def get_stats(self, project_path: str) -> GraphStats:
        """Read graph stats from graphify-out/graph.json."""
        graph_path = Path(project_path) / "graphify-out" / "graph.json"
        if not graph_path.exists():
            return GraphStats(nodes=0, edges=0, communities=0)

        data = await asyncio.to_thread(self._read_graph_json, graph_path)
        nodes = data.get("nodes", [])
        edges = data.get("edges", [])
        communities = data.get("communities", {})

        return GraphStats(
            nodes=len(nodes),
            edges=len(edges),
            communities=len(communities),
        )

    @staticmethod
    def _read_graph_json(path: Path) -> dict:
        with open(path) as f:
            return json.load(f)

    async def query(self, project_path: str, question: str) -> QueryResult:
        """Query the project graph."""
        if not self.available:
            return QueryResult(question=question, results=[])

        try:
            result = await asyncio.to_thread(
                self._run_graphify_query, project_path, question
            )
            return QueryResult(question=question, results=result)
        except Exception:
            return QueryResult(question=question, results=[])

    def _run_graphify_query(self, project_path: str, question: str) -> list[dict]:
        import subprocess
        result = subprocess.run(
            ["graphify", "query", question],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_path,
        )
        # Parse the query output into structured results
        lines = result.stdout.strip().split("\n")
        return [{"text": line} for line in lines if line.strip()]
```

**Step 4: Run test to verify pass**

```bash
pytest tests/test_graph_engine.py::test_get_stats_no_graph -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add daemon/graph_engine.py tests/test_graph_engine.py
git commit -m "feat: implement Graph Engine (Graphify wrapper)"
```

---

### Task 6: Implement Watcher (filesystem monitor)

**Objective:** Watchdog-based monitor for `~/.agentic-os/inbox/`. Emits events on new/modified files.

**Files:**
- Create: `daemon/watcher.py`
- Create: `tests/test_watcher.py`

**Step 1: Write watcher.py**

```python
"""Filesystem watcher for the agent inbox."""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Awaitable
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, str], Awaitable[None]]  # (project, filepath)


class InboxHandler(FileSystemEventHandler):
    """Watchdog handler that fires callbacks on inbox file events."""

    def __init__(self, callback: EventHandler, loop: asyncio.AbstractEventLoop):
        self.callback = callback
        self.loop = loop

    def on_created(self, event: FileCreatedEvent):
        if event.is_directory:
            return
        self._dispatch(event.src_path)

    def on_modified(self, event: FileModifiedEvent):
        if event.is_directory:
            return
        self._dispatch(event.src_path)

    def _dispatch(self, filepath: str):
        path = Path(filepath)
        # Extract project name from path: inbox/<project>/<file>
        parts = path.parts
        try:
            inbox_idx = parts.index("inbox")
            project = parts[inbox_idx + 1] if len(parts) > inbox_idx + 1 else "unknown"
        except ValueError:
            project = "unknown"
        asyncio.run_coroutine_threadsafe(
            self.callback(project, filepath), self.loop
        )


class InboxWatcher:
    """Watches ~/.agentic-os/inbox/ for new files."""

    def __init__(self, inbox_path: str = "~/.agentic-os/inbox"):
        self.inbox_path = Path(inbox_path).expanduser().resolve()
        self.observer: Optional[Observer] = None
        self._handler: Optional[InboxHandler] = None

    def start(self, callback: EventHandler, loop: asyncio.AbstractEventLoop):
        """Start watching the inbox directory."""
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self._handler = InboxHandler(callback, loop)
        self.observer = Observer()
        self.observer.schedule(self._handler, str(self.inbox_path), recursive=True)
        self.observer.start()
        logger.info(f"Watcher started on {self.inbox_path}")

    def stop(self):
        """Stop the watcher."""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            logger.info("Watcher stopped")

    @property
    def is_running(self) -> bool:
        return self.observer is not None and self.observer.is_alive()
```

**Step 2: Write test**

```python
"""Tests for the Watcher."""
import asyncio
import tempfile
from pathlib import Path
from daemon.watcher import InboxWatcher


@pytest.mark.asyncio
async def test_watcher_detects_new_file(tmp_path):
    """Watcher should fire callback when a file is created."""
    received = []

    async def callback(project: str, filepath: str):
        received.append((project, filepath))

    inbox = tmp_path / "inbox"
    inbox.mkdir()

    watcher = InboxWatcher(str(inbox))
    loop = asyncio.get_running_loop()
    watcher.start(callback, loop)

    # Write a file
    proj_dir = inbox / "test-project"
    proj_dir.mkdir()
    (proj_dir / "finding.md").write_text("# Test finding")

    # Wait for watchdog to pick it up
    await asyncio.sleep(0.5)

    watcher.stop()
    assert len(received) >= 1
    assert received[0][0] == "test-project"
```

**Step 3: Run test**

```bash
pytest tests/test_watcher.py::test_watcher_detects_new_file -v
```
Expected: PASS (may need watchdog installed: `pip install watchdog`)

**Step 4: Commit**

```bash
git add daemon/watcher.py tests/test_watcher.py
git commit -m "feat: implement inbox filesystem watcher"
```

---

### Task 7: Implement Router (event dispatcher)

**Objective:** Processes inbox events. Routes to graph updates, agent registration, findings ingestion.

**Files:**
- Create: `daemon/router.py`
- Create: `tests/test_router.py`

**Step 1: Write router.py**

```python
"""Event router — processes inbox files and dispatches actions."""

import asyncio
import json
import logging
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from daemon.registry import AgentRegistry
from daemon.graph_engine import GraphEngine
from daemon.models import (
    RegisterPayload, HeartbeatPayload, FindingFrontmatter,
    AgentInfo, AgentStatus, FindingType, BuildResult, WsEvent,
)

logger = logging.getLogger(__name__)

# Rate limiting: min seconds between graph updates per project
MIN_UPDATE_INTERVAL = 30


class Router:
    """Processes inbox events and dispatches to registry + graph engine."""

    def __init__(self, registry: AgentRegistry, graph_engine: GraphEngine):
        self.registry = registry
        self.graph = graph_engine
        self._last_update: dict[str, float] = {}  # project -> timestamp
        self._event_queue: asyncio.Queue[WsEvent] = asyncio.Queue()

    async def handle_file(self, project: str, filepath: str):
        """Route an inbox file to the correct handler."""
        path = Path(filepath)
        filename = path.name.lower()

        try:
            if filename == "register.json":
                await self._handle_register(project, path)
            elif filename == "heartbeat.json":
                await self._handle_heartbeat(project, path)
            elif filename.startswith("finding-") and filename.endswith(".md"):
                await self._handle_finding(project, path)
            elif filename.startswith("decision-") and filename.endswith(".md"):
                await self._handle_decision(project, path)
            else:
                logger.debug(f"Ignoring unknown file: {filename}")
                return

            # Move to processed
            processed_dir = path.parent / ".processed"
            processed_dir.mkdir(exist_ok=True)
            path.rename(processed_dir / path.name)

        except Exception as e:
            logger.error(f"Error handling {filepath}: {e}")
            await self._emit_error(project, filepath, str(e))

    async def _handle_register(self, project: str, path: Path):
        payload = RegisterPayload(**json.loads(path.read_text()))
        agent_id = f"{payload.agent}-{project}"

        agent = AgentInfo(
            agent_id=agent_id,
            agent_name=payload.agent,
            version=payload.version,
            project=project,
            capabilities=payload.capabilities,
            status=AgentStatus.ONLINE,
            last_heartbeat=datetime.now(timezone.utc),
        )
        await self.registry.upsert_agent(agent)
        await self.registry.upsert_project(project, payload.project_path)

        # Trigger initial graph build
        if self.graph.available:
            asyncio.create_task(self._build_project(project, payload.project_path))

        await self._emit_event("agent:online", project, {
            "agent": payload.agent,
            "capabilities": payload.capabilities,
        })

    async def _handle_heartbeat(self, project: str, path: Path):
        payload = HeartbeatPayload(**json.loads(path.read_text()))
        agent_id = f"{payload.agent}-{project}"
        agent = await self.registry.get_agent(agent_id)
        if agent:
            agent.last_heartbeat = payload.timestamp
            agent.status = AgentStatus.ONLINE
            await self.registry.upsert_agent(agent)

    async def _handle_finding(self, project: str, path: Path):
        content = path.read_text()
        frontmatter = self._parse_frontmatter(content)

        # If finding references code files, queue incremental update
        if frontmatter.files and self._can_update(project):
            project_info = await self.registry.get_project(project)
            if project_info:
                asyncio.create_task(
                    self._update_project(project, project_info.project_path, frontmatter)
                )

        await self._emit_event("finding:ingested", project, {
            "file": path.name,
            "type": frontmatter.type.value,
        })

    async def _handle_decision(self, project: str, path: Path):
        content = path.read_text()
        frontmatter = self._parse_frontmatter(content)
        frontmatter.type = FindingType.ARCHITECTURE_DECISION

        await self._emit_event("finding:ingested", project, {
            "file": path.name,
            "type": "architecture-decision",
        })

    def _parse_frontmatter(self, content: str) -> FindingFrontmatter:
        """Parse YAML frontmatter from markdown."""
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                data = yaml.safe_load(parts[1])
                return FindingFrontmatter(**data)
        return FindingFrontmatter(agent="unknown", project="unknown")

    def _can_update(self, project: str) -> bool:
        now = datetime.now(timezone.utc).timestamp()
        last = self._last_update.get(project, 0)
        if now - last >= MIN_UPDATE_INTERVAL:
            self._last_update[project] = now
            return True
        return False

    async def _build_project(self, project: str, project_path: str):
        result = await self.graph.build_project(project_path)
        await self._emit_event("graph:updated", project, {
            "nodes_added": result.nodes,
            "edges_added": result.edges,
            "status": result.status,
        })

    async def _update_project(self, project: str, project_path: str, finding: FindingFrontmatter):
        result = await self.graph.update_project(project_path, finding.files)
        await self._emit_event("graph:updated", project, {
            "nodes_added": result.nodes,
            "edges_added": result.edges,
            "agent": finding.agent,
        })

    async def _emit_event(self, event: str, project: str, data: dict):
        ws_event = WsEvent(event=event, project=project, data=data)
        await self._event_queue.put(ws_event)

    async def _emit_error(self, project: str, filepath: str, message: str):
        await self._emit_event("error", project, {
            "file": filepath,
            "message": message,
        })

    @property
    def events(self) -> asyncio.Queue[WsEvent]:
        return self._event_queue
```

**Step 2: Commit**

```bash
git add daemon/router.py
git commit -m "feat: implement inbox event router"
```

---

## Phase 4: Daemon — API Server

### Task 8: Implement FastAPI routes + WebSocket

**Objective:** REST API and WebSocket endpoint for the dashboard.

**Files:**
- Create: `daemon/api.py`

**Step 1: Write api.py**

```python
"""FastAPI application for the Agentic OS daemon."""

import asyncio
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from daemon.registry import AgentRegistry
from daemon.graph_engine import GraphEngine
from daemon.router import Router
from daemon.watcher import InboxWatcher
from daemon.models import WsEvent
import logging

logger = logging.getLogger(__name__)

# Global state
registry: AgentRegistry = None
graph_engine: GraphEngine = None
router: Router = None
watcher: InboxWatcher = None
connected_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start watcher on startup, clean up on shutdown."""
    global registry, graph_engine, router, watcher

    registry = AgentRegistry()
    await registry.initialize()

    graph_engine = GraphEngine()
    router = Router(registry, graph_engine)

    watcher = InboxWatcher()
    loop = asyncio.get_running_loop()
    watcher.start(router.handle_file, loop)

    # Background task: broadcast events to WebSocket clients
    asyncio.create_task(_broadcast_events())

    logger.info("Agentic OS daemon started")
    yield
    watcher.stop()
    await registry.close()
    logger.info("Agentic OS daemon stopped")


app = FastAPI(title="Agentic OS", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/projects")
async def list_projects():
    """List all tracked projects."""
    projects = await registry.list_projects()
    return {"projects": [p.model_dump() for p in projects]}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get project details with graph stats and agents."""
    project = await registry.get_project(project_id)
    if not project:
        return {"error": "Project not found"}, 404

    stats = await graph_engine.get_stats(project.project_path)
    agents = await registry.list_agents(project_id)

    return {
        "project": project.model_dump(),
        "graph": stats.model_dump(),
        "agents": [a.model_dump() for a in agents],
    }


@app.get("/api/projects/{project_id}/graph")
async def get_graph_stats(project_id: str):
    """Get graph statistics for a project."""
    project = await registry.get_project(project_id)
    if not project:
        return {"error": "Project not found"}, 404
    stats = await graph_engine.get_stats(project.project_path)
    return stats.model_dump()


@app.get("/api/projects/{project_id}/query")
async def query_graph(project_id: str, q: str = ""):
    """Query the project knowledge graph."""
    if not q:
        return {"error": "Missing query parameter 'q'"}, 400
    project = await registry.get_project(project_id)
    if not project:
        return {"error": "Project not found"}, 404
    result = await graph_engine.query(project.project_path, q)
    return result.model_dump()


@app.get("/api/projects/{project_id}/agents")
async def list_agents(project_id: str):
    """List agents for a project."""
    agents = await registry.list_agents(project_id)
    return {"agents": [a.model_dump() for a in agents]}


@app.post("/api/projects/{project_id}/rebuild")
async def rebuild_graph(project_id: str):
    """Force a full graph rebuild."""
    project = await registry.get_project(project_id)
    if not project:
        return {"error": "Project not found"}, 404
    result = await graph_engine.build_project(project.project_path)
    return result.model_dump()


@app.get("/api/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "graphify_available": graph_engine.available,
        "watcher_running": watcher.is_running if watcher else False,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for live event streaming."""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            # Keep connection alive, events come from broadcast
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def _broadcast_events():
    """Broadcast router events to all connected WebSocket clients."""
    while True:
        event: WsEvent = await router.events.get()
        disconnected = []
        for client in connected_clients:
            try:
                await client.send_text(event.model_dump_json())
            except Exception:
                disconnected.append(client)
        for client in disconnected:
            if client in connected_clients:
                connected_clients.remove(client)
```

**Step 2: Commit**

```bash
git add daemon/api.py
git commit -m "feat: implement FastAPI routes + WebSocket"
```

---

### Task 9: Implement daemon entry point

**Objective:** `daemon/main.py` — uvicorn startup with CLI.

**Files:**
- Create: `daemon/main.py`

**Step 1: Write main.py**

```python
"""Agentic OS daemon entry point."""

import argparse
import logging
import uvicorn


def main():
    parser = argparse.ArgumentParser(description="Agentic OS Daemon")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8472, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--log-level", default="info", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "daemon.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
```

**Step 2: Verify the CLI works**

```bash
cd /Users/mohamedabdulrahman/mohamed-hussien/my-projects/agentic-os
source .venv/bin/activate
python -m daemon.main --help
```
Expected: shows argparse help with --host, --port, --reload, --log-level

**Step 3: Install as CLI command**

The `pyproject.toml` already has `[project.scripts]` pointing to `daemon.main:main`. Verify:

```bash
pip install -e .
agentic-os --help
```
Expected: same help output

**Step 4: Commit**

```bash
git add daemon/main.py
git commit -m "feat: add daemon entry point with CLI"
```

---

## Phase 5: Dashboard

### Task 10: Create dashboard layout + sidebar

**Objective:** Root layout with sidebar navigation and WebSocket provider.

**Files:**
- Modify: `dashboard/app/layout.tsx`
- Create: `dashboard/components/sidebar.tsx`
- Create: `dashboard/lib/use-websocket.ts`

**Step 1: Write WebSocket hook**

```typescript
// dashboard/lib/use-websocket.ts
"use client";

import { useEffect, useRef, useState, useCallback } from "react";

interface WsEvent {
  event: string;
  project: string;
  data: Record<string, unknown>;
  timestamp: string;
}

export function useWebSocket() {
  const [lastEvent, setLastEvent] = useState<WsEvent | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const listenersRef = useRef<Map<string, Set<(data: WsEvent) => void>>>(new Map());

  useEffect(() => {
    const ws = new WebSocket("ws://localhost:8472/ws");
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onmessage = (msg) => {
      try {
        const event: WsEvent = JSON.parse(msg.data);
        setLastEvent(event);
        // Notify type-specific listeners
        const typeListeners = listenersRef.current.get(event.event);
        if (typeListeners) {
          typeListeners.forEach((fn) => fn(event));
        }
        // Notify project-specific listeners
        const projListeners = listenersRef.current.get(`project:${event.project}`);
        if (projListeners) {
          projListeners.forEach((fn) => fn(event));
        }
      } catch {}
    };

    return () => ws.close();
  }, []);

  const subscribe = useCallback(
    (key: string, fn: (data: WsEvent) => void) => {
      if (!listenersRef.current.has(key)) {
        listenersRef.current.set(key, new Set());
      }
      listenersRef.current.get(key)!.add(fn);
      return () => {
        listenersRef.current.get(key)?.delete(fn);
      };
    },
    []
  );

  return { lastEvent, connected, subscribe };
}
```

**Step 2: Write sidebar component**

```tsx
// dashboard/components/sidebar.tsx
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, FolderGit2, Activity } from "lucide-react";

export function Sidebar() {
  const pathname = usePathname();

  const links = [
    { href: "/", label: "Projects", icon: Home },
    { href: "/activity", label: "Activity", icon: Activity },
  ];

  return (
    <aside className="w-64 border-r border-zinc-800 bg-zinc-950 min-h-screen p-4">
      <div className="mb-8">
        <h1 className="text-lg font-bold text-zinc-100">Agentic OS</h1>
        <p className="text-xs text-zinc-500">Agent Memory Fabric</p>
      </div>
      <nav className="space-y-1">
        {links.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                active
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
```

**Step 3: Update root layout**

```tsx
// dashboard/app/layout.tsx
import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";

const geistMono = Geist_Mono({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Agentic OS",
  description: "Unified agent memory fabric",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${geistMono.className} bg-zinc-950 text-zinc-100 antialiased`}>
        <div className="flex">
          <Sidebar />
          <main className="flex-1 p-6">{children}</main>
        </div>
      </body>
    </html>
  );
}
```

**Step 4: Verify build**

```bash
cd dashboard && npm run build
```
Expected: successful build

**Step 5: Commit**

```bash
git add dashboard/
git commit -m "feat: add dashboard layout with sidebar and WebSocket hook"
```

---

### Task 11: Create API client for daemon

**Objective:** Typed fetch wrapper for the daemon API.

**Files:**
- Create: `dashboard/lib/api.ts`

**Step 1: Write api.ts**

```typescript
// dashboard/lib/api.ts

const BASE_URL = "http://localhost:8472";

export interface ProjectSummary {
  project: {
    project_id: string;
    project_name: string;
    project_path: string;
    node_count: number;
    edge_count: number;
    community_count: number;
    last_graph_update: string | null;
    active_agents: number;
    total_findings: number;
  };
  graph: {
    nodes: number;
    edges: number;
    communities: number;
  } | null;
  agents: AgentInfo[];
}

export interface AgentInfo {
  agent_id: string;
  agent_name: string;
  version: string;
  project: string;
  capabilities: string[];
  status: "online" | "offline" | "working";
  last_heartbeat: string | null;
  registered_at: string;
}

export interface GraphStats {
  nodes: number;
  edges: number;
  communities: number;
}

export interface QueryResult {
  question: string;
  results: { text: string }[];
  communities: string[];
}

async function fetchApi<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function listProjects(): Promise<{ projects: ProjectSummary["project"][] }> {
  return fetchApi("/api/projects");
}

export async function getProject(id: string): Promise<ProjectSummary> {
  return fetchApi(`/api/projects/${id}`);
}

export async function getGraphStats(id: string): Promise<GraphStats> {
  return fetchApi(`/api/projects/${id}/graph`);
}

export async function queryGraph(id: string, q: string): Promise<QueryResult> {
  return fetchApi(`/api/projects/${id}/query?q=${encodeURIComponent(q)}`);
}

export async function rebuildGraph(id: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${id}/rebuild`, { method: "POST" });
  return res.json();
}
```

**Step 2: Commit**

```bash
git add dashboard/lib/api.ts
git commit -m "feat: add typed API client for daemon"
```

---

### Task 12: Build Project Overview page

**Objective:** Landing page showing all tracked projects as cards.

**Files:**
- Create: `dashboard/app/page.tsx`
- Create: `dashboard/components/project-card.tsx`

**Step 1: Write ProjectCard component**

```tsx
// dashboard/components/project-card.tsx
import Link from "next/link";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

interface ProjectCardProps {
  project: {
    project_id: string;
    project_name: string;
    node_count: number;
    edge_count: number;
    community_count: number;
    active_agents: number;
    last_graph_update: string | null;
  };
}

export function ProjectCard({ project }: ProjectCardProps) {
  const timeAgo = project.last_graph_update
    ? getTimeAgo(new Date(project.last_graph_update))
    : "never";

  return (
    <Link href={`/projects/${project.project_id}`}>
      <Card className="bg-zinc-900 border-zinc-800 hover:border-zinc-700 transition-colors cursor-pointer">
        <CardHeader>
          <CardTitle className="text-zinc-100">{project.project_name}</CardTitle>
          <CardDescription className="text-zinc-500">{project.project_id}</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-4 text-sm">
            <div>
              <span className="text-emerald-400 font-mono">{project.node_count}</span>
              <span className="text-zinc-600 ml-1">nodes</span>
            </div>
            <div>
              <span className="text-blue-400 font-mono">{project.edge_count}</span>
              <span className="text-zinc-600 ml-1">edges</span>
            </div>
            <div>
              <span className="text-purple-400 font-mono">{project.community_count}</span>
              <span className="text-zinc-600 ml-1">communities</span>
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            {project.active_agents > 0 ? (
              <Badge variant="default" className="bg-emerald-900 text-emerald-300 text-xs">
                {project.active_agents} agent{project.active_agents !== 1 ? "s" : ""} active
              </Badge>
            ) : (
              <Badge variant="outline" className="text-zinc-600 text-xs">
                no agents
              </Badge>
            )}
            <span className="text-xs text-zinc-600 self-center">Updated {timeAgo}</span>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}

function getTimeAgo(date: Date): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}
```

**Step 2: Write Projects page**

```tsx
// dashboard/app/page.tsx
"use client";

import { useEffect, useState } from "react";
import { listProjects } from "@/lib/api";
import { ProjectCard } from "@/components/project-card";
import { useWebSocket } from "@/lib/use-websocket";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const { lastEvent } = useWebSocket();

  useEffect(() => {
    listProjects()
      .then((data) => setProjects(data.projects || []))
      .finally(() => setLoading(false));
  }, []);

  // Refresh on graph updates
  useEffect(() => {
    if (lastEvent?.event === "graph:updated") {
      listProjects().then((data) => setProjects(data.projects || []));
    }
  }, [lastEvent]);

  if (loading) {
    return <div className="text-zinc-500">Loading projects...</div>;
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Projects</h2>
      {projects.length === 0 ? (
        <div className="text-zinc-500">
          <p>No projects tracked yet.</p>
          <p className="text-sm mt-2">
            Agents will appear here when they register by writing to{" "}
            <code className="text-zinc-400">~/.agentic-os/inbox/</code>
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map((p) => (
            <ProjectCard key={p.project_id} project={p} />
          ))}
        </div>
      )}
    </div>
  );
}
```

**Step 3: Verify build**

```bash
cd dashboard && npm run build
```
Expected: successful build

**Step 4: Commit**

```bash
git add dashboard/
git commit -m "feat: add project overview page with cards"
```

---

### Task 13: Build Project Detail page

**Objective:** Individual project view with graph stats, agents, and activity.

**Files:**
- Create: `dashboard/app/projects/[id]/page.tsx`
- Create: `dashboard/components/graph-stats.tsx`
- Create: `dashboard/components/agent-badge.tsx`
- Create: `dashboard/components/activity-feed.tsx`

**Step 1: Write AgentBadge**

```tsx
// dashboard/components/agent-badge.tsx
import { Badge } from "@/components/ui/badge";

interface AgentBadgeProps {
  agent: {
    agent_name: string;
    status: "online" | "offline" | "working";
    capabilities: string[];
    last_heartbeat: string | null;
  };
}

export function AgentBadge({ agent }: AgentBadgeProps) {
  const statusColor = {
    online: "bg-emerald-900 text-emerald-300",
    working: "bg-amber-900 text-amber-300",
    offline: "bg-zinc-800 text-zinc-500",
  };

  return (
    <div className="flex items-center gap-3 py-2">
      <div className={`w-2 h-2 rounded-full ${agent.status === "online" ? "bg-emerald-400" : agent.status === "working" ? "bg-amber-400" : "bg-zinc-600"}`} />
      <div className="flex-1">
        <div className="text-sm text-zinc-200">{agent.agent_name}</div>
        <div className="text-xs text-zinc-500">
          {agent.capabilities.join(", ")}
        </div>
      </div>
      <Badge className={statusColor[agent.status]} variant="outline">
        {agent.status}
      </Badge>
    </div>
  );
}
```

**Step 2: Write GraphStats component**

```tsx
// dashboard/components/graph-stats.tsx
interface GraphStatsProps {
  stats: {
    nodes: number;
    edges: number;
    communities: number;
  };
}

export function GraphStats({ stats }: GraphStatsProps) {
  return (
    <div className="grid grid-cols-3 gap-4">
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-center">
        <div className="text-2xl font-mono text-emerald-400">{stats.nodes}</div>
        <div className="text-xs text-zinc-500 mt-1">Nodes</div>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-center">
        <div className="text-2xl font-mono text-blue-400">{stats.edges}</div>
        <div className="text-xs text-zinc-500 mt-1">Edges</div>
      </div>
      <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 text-center">
        <div className="text-2xl font-mono text-purple-400">{stats.communities}</div>
        <div className="text-xs text-zinc-500 mt-1">Communities</div>
      </div>
    </div>
  );
}
```

**Step 3: Write ActivityFeed**

```tsx
// dashboard/components/activity-feed.tsx
"use client";

import { useEffect, useState } from "react";
import { useWebSocket } from "@/lib/use-websocket";
import { ScrollArea } from "@/components/ui/scroll-area";

interface ActivityEvent {
  id: string;
  timestamp: string;
  event: string;
  data: Record<string, unknown>;
}

export function ActivityFeed({ projectId }: { projectId: string }) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const { subscribe } = useWebSocket();

  useEffect(() => {
    return subscribe(`project:${projectId}`, (event) => {
      setEvents((prev) => [
        {
          id: crypto.randomUUID(),
          timestamp: event.timestamp,
          event: event.event,
          data: event.data,
        },
        ...prev,
      ].slice(0, 50));
    });
  }, [projectId, subscribe]);

  return (
    <ScrollArea className="h-64">
      <div className="space-y-2">
        {events.length === 0 && (
          <div className="text-sm text-zinc-600">Waiting for activity...</div>
        )}
        {events.map((e) => (
          <div key={e.id} className="text-sm text-zinc-400 border-b border-zinc-800/50 pb-2">
            <span className="text-zinc-600 text-xs">
              {new Date(e.timestamp).toLocaleTimeString()}
            </span>{" "}
            <span className="text-zinc-300">{formatEvent(e)}</span>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}

function formatEvent(event: ActivityEvent): string {
  switch (event.event) {
    case "agent:online":
      return `${event.data.agent} came online`;
    case "graph:updated":
      return `Graph updated: +${event.data.nodes_added || 0} nodes`;
    case "finding:ingested":
      return `Finding ingested: ${event.data.file}`;
    default:
      return event.event;
  }
}
```

**Step 4: Write Project Detail page**

```tsx
// dashboard/app/projects/[id]/page.tsx
"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getProject } from "@/lib/api";
import { GraphStats } from "@/components/graph-stats";
import { AgentBadge } from "@/components/agent-badge";
import { ActivityFeed } from "@/components/activity-feed";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getProject(id)
      .then(setData)
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="text-zinc-500">Loading...</div>;
  if (!data) return <div className="text-zinc-500">Project not found</div>;

  const { project, graph, agents } = data;

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-2xl font-bold">{project.project_name}</h2>
          <p className="text-sm text-zinc-500">{project.project_path}</p>
        </div>
        <Link href={`/projects/${id}/graph`}>
          <Button variant="outline" size="sm">
            Graph Explorer <ArrowRight className="w-3 h-3 ml-2" />
          </Button>
        </Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">Graph Overview</h3>
          {graph ? <GraphStats stats={graph} /> : <p className="text-zinc-600 text-sm">No graph data yet</p>}
        </div>
        <div>
          <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">Agents</h3>
          {agents.length === 0 ? (
            <p className="text-zinc-600 text-sm">No agents registered</p>
          ) : (
            <div className="divide-y divide-zinc-800">
              {agents.map((a: any) => (
                <AgentBadge key={a.agent_id} agent={a} />
              ))}
            </div>
          )}
        </div>
        <div className="lg:col-span-2">
          <h3 className="text-sm font-semibold text-zinc-400 uppercase mb-3">Live Activity</h3>
          <ActivityFeed projectId={id} />
        </div>
      </div>
    </div>
  );
}
```

**Step 5: Verify build**

```bash
cd dashboard && npm run build
```
Expected: successful build

**Step 6: Commit**

```bash
git add dashboard/
git commit -m "feat: add project detail page with live activity"
```

---

### Task 14: Build Graph Explorer page

**Objective:** Query interface for the project knowledge graph.

**Files:**
- Create: `dashboard/app/projects/[id]/graph/page.tsx`

**Step 1: Write Graph Explorer page**

```tsx
// dashboard/app/projects/[id]/graph/page.tsx
"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { queryGraph } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Search, Loader2 } from "lucide-react";

export default function GraphExplorerPage() {
  const { id } = useParams<{ id: string }>();
  const [question, setQuestion] = useState("");
  const [results, setResults] = useState<{ text: string }[]>([]);
  const [loading, setLoading] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    try {
      const data = await queryGraph(id, question);
      setResults(data.results || []);
    } catch {
      setResults([{ text: "Query failed. Is the daemon running?" }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">Graph Explorer</h2>
      <p className="text-sm text-zinc-500 mb-6">
        Ask questions about the {id} codebase knowledge graph
      </p>

      <form onSubmit={handleSearch} className="flex gap-2 mb-6">
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="e.g. What calls the auth controller?"
          className="bg-zinc-900 border-zinc-700 text-zinc-200 flex-1"
        />
        <Button type="submit" disabled={loading}>
          {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
        </Button>
      </form>

      {results.length > 0 && (
        <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-4">
          <h3 className="text-sm text-zinc-400 mb-3">
            Results for &ldquo;{question}&rdquo;
          </h3>
          <div className="space-y-2">
            {results.map((r, i) => (
              <div key={i} className="text-sm text-zinc-300 font-mono pl-4 border-l-2 border-zinc-700">
                {r.text}
              </div>
            ))}
          </div>
        </div>
      )}

      {results.length === 0 && !loading && (
        <div className="text-sm text-zinc-600">
          <p>Try asking:</p>
          <ul className="list-disc pl-5 mt-2 space-y-1">
            <li>What are the main modules?</li>
            <li>Show me the callers of the API handler</li>
            <li>What community has the most nodes?</li>
            <li>Find surprising connections</li>
          </ul>
        </div>
      )}
    </div>
  );
}
```

**Step 2: Verify build**

```bash
cd dashboard && npm run build
```
Expected: successful build

**Step 3: Commit**

```bash
git add dashboard/
git commit -m "feat: add graph explorer with query interface"
```

---

## Phase 6: Integration & Polish

### Task 15: End-to-end smoke test

**Objective:** Start daemon, write inbox files, verify dashboard sees the project.

**Files:**
- Create: `scripts/smoke-test.sh`

**Step 1: Write smoke test script**

```bash
#!/bin/bash
# scripts/smoke-test.sh — end-to-end test for Agentic OS

set -e

AGENTIC_OS_HOME="$HOME/.agentic-os"
INBOX="$AGENTIC_OS_HOME/inbox/test-project"
API="http://localhost:8472"

echo "=== Agentic OS Smoke Test ==="

# 1. Start daemon in background
echo "[1/5] Starting daemon..."
cd "$(dirname "$0")/.."
source .venv/bin/activate
agentic-os --port 8472 &
DAEMON_PID=$!
sleep 3

# 2. Health check
echo "[2/5] Health check..."
curl -s "$API/api/health" | grep '"status":"ok"'

# 3. Register an agent
echo "[3/5] Registering test agent..."
mkdir -p "$INBOX"
cat > "$INBOX/register.json" << 'EOF'
{
  "agent": "test-agent",
  "version": "1.0.0",
  "project": "test-project",
  "project_path": "/tmp/test-project",
  "capabilities": ["testing"]
}
EOF
sleep 1

# 4. Check project appears
echo "[4/5] Checking project list..."
curl -s "$API/api/projects" | grep "test-project"

# 5. Send heartbeat
echo "[5/5] Sending heartbeat..."
cat > "$INBOX/heartbeat.json" << EOF
{
  "agent": "test-agent",
  "project": "test-project",
  "status": "smoke testing",
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
sleep 1

# Check agent appears
curl -s "$API/api/projects/test-project/agents" | grep "test-agent"

# Cleanup
kill $DAEMON_PID 2>/dev/null || true
echo ""
echo "=== All smoke tests passed! ==="
```

**Step 2: Run smoke test**

```bash
chmod +x scripts/smoke-test.sh
bash scripts/smoke-test.sh
```
Expected: all steps pass, daemon starts, agent registers, API responds

**Step 3: Commit**

```bash
mkdir -p scripts
git add scripts/smoke-test.sh
git commit -m "test: add end-to-end smoke test"
```

---

### Task 16: Final README and documentation

**Objective:** Write project README with setup, usage, and architecture.

**Files:**
- Modify: `README.md`

**Step 1: Write README**

```markdown
# Agentic OS

Unified agent memory fabric. Links all AI coding agents on a single machine through a shared Graphify-powered knowledge graph. Agents communicate via filesystem hooks. Next.js dashboard for monitoring and querying.

## Architecture

```
Browser :3000 → Next.js Dashboard
                    ↓ REST + WebSocket
Agentic OS Daemon (Python/FastAPI) :8472
  ├── Watcher (watchdog) → ~/.agentic-os/inbox/
  ├── Router (dispatcher)
  ├── Graph Engine (Graphify)
  └── Agent Registry (SQLite)
        ↑ filesystem writes
Claude Code · Codex · Hermes
```

## Quick Start

```bash
# Install
git clone <repo>
cd agentic-os
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Start daemon
agentic-os

# In another terminal, start dashboard
cd dashboard && npm install && npm run dev
```

Open http://localhost:3000

## How Agents Connect

Agents write files to `~/.agentic-os/inbox/<project>/`:

```bash
# Register
echo '{"agent":"claude-code","version":"2.1","project":"noor","project_path":"~/projects/Noor","capabilities":["code-analysis"]}' > ~/.agentic-os/inbox/noor/register.json

# Heartbeat (every 60s)
echo '{"agent":"claude-code","project":"noor","status":"analyzing","timestamp":"2026-06-25T14:30:00Z"}' > ~/.agentic-os/inbox/noor/heartbeat.json

# Share findings
cat > ~/.agentic-os/inbox/noor/finding-auth.md << 'EOF'
---
agent: claude-code
project: noor
type: code-analysis
files: [src/auth.py]
---
# Auth Module
JWT with Redis sessions...
EOF
```

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | /api/projects | List projects |
| GET | /api/projects/:id | Project detail + graph + agents |
| GET | /api/projects/:id/graph | Graph stats |
| GET | /api/projects/:id/query?q= | Query graph |
| GET | /api/projects/:id/agents | Agent list |
| POST | /api/projects/:id/rebuild | Force rebuild |
| WS | /ws | Live events |

## Development

```bash
# Daemon
pip install -e ".[dev]"
pytest tests/ -v

# Dashboard
cd dashboard && npm run dev
```
```

**Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add comprehensive README"
```

---

## Implementation Order

1. Task 1 → Task 2 (scaffold both projects)
2. Task 3 → Task 4 (data layer)
3. Task 5 → Task 6 → Task 7 (core engine)
4. Task 8 → Task 9 (API server)
5. Task 10 → Task 11 → Task 12 → Task 13 → Task 14 (dashboard)
6. Task 15 → Task 16 (integration + docs)

Total: 16 tasks. Each task 2-5 minutes of focused work.
