"""FastAPI application for the Loom daemon."""

import os
import uuid
from typing import Optional

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from daemon.registry import AgentRegistry, ProjectExistsError
from daemon.graph_engine import GraphEngine
from daemon.router import Router
from daemon.watcher import InboxWatcher
from daemon.traces import TraceCapture
from daemon.snapshots import SnapshotManager
from daemon.models import WsEvent, ProjectCreatePayload, DispatchRequest, TaskPayload, RegisterAgentPayload
from daemon.models import (
    AgentTaskCreatePayload, AgentTaskUpdatePayload, AgentTaskRecord, AgentStatus,
)

logger = logging.getLogger(__name__)

# Global state
registry: Optional[AgentRegistry] = None
graph_engine: Optional[GraphEngine] = None
router: Optional[Router] = None
watcher: Optional[InboxWatcher] = None
trace_capture: Optional[TraceCapture] = None
snapshot_manager: Optional[SnapshotManager] = None
pattern_repo: Optional = None  # PatternRepository (lazy)
audit_trail: Optional = None     # AuditTrail (lazy)
temporal_tracker: Optional = None  # TemporalTracker
doc_ingestor: Optional = None      # DocumentIngestor
eval_engine: Optional = None  # EvalEngine (lazy import)
connected_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start watcher on startup, clean up on shutdown.

    Honors globals pre-set by tests: if a registry/graph_engine has been
    injected, the lifespan reuses it and skips the filesystem watcher /
    broadcast task (which depend on real ``~/.loom`` state).
    """
    global registry, graph_engine, router, watcher, trace_capture, snapshot_manager

    # Tests may inject a temp-backed registry/graph_engine beforehand.
    test_mode = registry is not None

    if registry is None:
        registry = AgentRegistry()
    if graph_engine is None:
        graph_engine = GraphEngine()
    if not getattr(registry, "db", None):
        await registry.initialize()
    if router is None:
        router = Router(registry, graph_engine)
    if trace_capture is None:
        trace_capture = TraceCapture()
    if snapshot_manager is None:
        snapshot_manager = SnapshotManager()

    if not test_mode:
        watcher = InboxWatcher()
        loop = asyncio.get_running_loop()
        watcher.start(router.handle_file, loop)
        # Background task: broadcast events to WebSocket clients
        asyncio.create_task(_broadcast_events())

    logger.info("Loom daemon started")
    yield
    if watcher is not None:
        watcher.stop()
    await registry.close()
    logger.info("Loom daemon stopped")


app = FastAPI(title="Loom", version="0.1.0", lifespan=lifespan)

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
        raise HTTPException(status_code=404, detail="Project not found")

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
        raise HTTPException(status_code=404, detail="Project not found")
    stats = await graph_engine.get_stats(project.project_path)
    return stats.model_dump()

@app.get("/api/projects/{project_id}/graph/topology")
async def get_graph_topology(project_id: str):
    """Get full graph topology for visualization."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    topology = await graph_engine.get_topology(project.project_path)
    return topology

@app.get("/api/projects/{project_id}/graph/communities")
async def get_graph_communities(project_id: str):
    """Get community list for graph filter."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    communities = await graph_engine.get_communities(project.project_path)
    return {"communities": communities}

@app.get("/api/projects/{project_id}/graph/flows")
async def get_graph_flows(project_id: str):
    """Get execution flows for graph highlighting."""
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    flows = await graph_engine.get_flows(project.project_path)
    return {"flows": flows}


@app.get("/api/projects/{project_id}/query")
async def query_graph(project_id: str, q: str = ""):
    """Query the project knowledge graph."""
    if not q:
        raise HTTPException(status_code=400, detail="Missing query parameter 'q'")
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    result = await graph_engine.query(project.project_path, q)
    return result.model_dump()

@app.post("/api/projects/{project_id}/dispatch")
async def dispatch_task(project_id: str, payload: DispatchRequest):
    """Dispatch a task to an agent.

    Persistence is owned here: we write the inbox file (so an offline agent /
    the watcher can pick it up) AND insert the registry row atomically. The
    watcher's ``_handle_task`` is idempotent, so reprocessing the dropped file
    is a no-op rather than a duplicate insert / duplicate broadcast.
    """
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    task_id = str(uuid.uuid4())
    task_payload = TaskPayload(
        task_id=task_id,
        target_agent=payload.target_agent,
        instruction=payload.instruction,
        priority=payload.priority,
    )

    inbox_dir = os.path.expanduser(f"~/.loom/inbox/{project_id}")
    os.makedirs(inbox_dir, exist_ok=True)
    task_path = os.path.join(inbox_dir, f"task-{task_id}.json")
    with open(task_path, "w") as f:
        f.write(task_payload.model_dump_json())

    created = await registry.create_task(
        task_id, project_id, payload.target_agent, payload.instruction, payload.priority
    )

    # Only emit on the first creation — the watcher path (and any retry)
    # returns False from create_task and stays silent.
    if created and router:
        await router._emit_event("agent:dispatched", project_id, {
            "task_id": task_id,
            "target_agent": payload.target_agent,
            "instruction": payload.instruction,
        })

    return {"task_id": task_id, "status": "dispatched"}

@app.get("/api/projects/{project_id}/dispatches")
async def list_dispatches(project_id: str):
    """List task dispatches for a project."""
    tasks = await registry.list_tasks(project_id)
    return {"dispatches": tasks}


@app.post("/api/projects/{project_id}/register-agent")
async def register_agent(project_id: str, payload: RegisterAgentPayload):
    """Register a coding agent for a project.

    Dual-write pattern (same as dispatch): writes ``register.json`` to the
    inbox so the watcher can reprocess it on restart, AND calls the router
    directly so the agent appears and the graph build starts *immediately*.
    Idempotent — re-registering the same agent is a no-op.
    """
    from pathlib import Path

    # Validate the project path exists
    expanded = os.path.expanduser(payload.project_path)
    if not os.path.isdir(expanded):
        raise HTTPException(status_code=400, detail="Project path does not exist")

    # Write register.json to the inbox
    inbox_dir = os.path.expanduser(f"~/.loom/inbox/{project_id}")
    os.makedirs(inbox_dir, exist_ok=True)
    register_path = os.path.join(inbox_dir, "register.json")

    import json
    register_doc = {
        "agent": payload.agent,
        "version": payload.version,
        "project": project_id,
        "project_path": payload.project_path,
        "capabilities": payload.capabilities,
    }
    with open(register_path, "w") as f:
        json.dump(register_doc, f)

    # Process immediately through the router — the agent is registered and
    # the graph build starts right now, not on the next watcher tick.
    if router:
        await router.handle_file(project_id, register_path)

    return {
        "status": "registered",
        "agent": payload.agent,
        "project": project_id,
    }


@app.get("/api/projects/{project_id}/agents")
async def list_agents(project_id: str):
    """List agents for a project."""
    agents = await registry.list_agents(project_id)
    return {"agents": [a.model_dump() for a in agents]}


@app.delete("/api/projects/{project_id}/agents/{agent_id}")
async def delete_agent(project_id: str, agent_id: str):
    """Remove an agent from a project."""
    deleted = await registry.delete_agent(agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    if router:
        await router._emit_event("agent:offline", project_id, {
            "agent_id": agent_id,
        })
    return {"deleted": True, "agent_id": agent_id}


@app.get("/api/agents/known")
async def list_known_agents():
    """Return known agent types and which are detected on this machine."""
    from daemon.known_agents import get_known_agents, detect_installed
    known = get_known_agents()
    installed = detect_installed()
    # Merge: mark each known agent as installed if detected
    for agent in known:
        agent["installed"] = agent["name"] in installed
    return {"agents": known}


@app.get("/api/projects/{project_id}/knowledge")
async def get_project_knowledge(project_id: str):
    """List knowledge sources discovered in a project."""
    from daemon.project_knowledge import discover_knowledge_sources
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    sources = discover_knowledge_sources(project.project_path)
    return {
        "project_id": project_id,
        "sources": [
            {
                "source_type": s.source_type,
                "display_name": s.display_name,
                "description": s.description,
                "used_by": s.used_by,
                "found": s.found,
                "path": s.path,
                "size_bytes": s.size_bytes,
            }
            for s in sources
        ],
    }


@app.post("/api/projects/{project_id}/knowledge/scan")
async def scan_project_knowledge(project_id: str):
    """Scan and ingest all knowledge sources in a project."""
    from daemon.project_knowledge import ingest_all_sources
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    results = await ingest_all_sources(project_id, project.project_path)
    if router:
        await router._emit_event("knowledge:scanned", project_id, {
            "sources_found": sum(1 for r in results if r.get("found", True)),
            "sources_ingested": sum(1 for r in results if r.get("status") == "ingested"),
        })
    return {"project_id": project_id, "results": results}


@app.get("/api/projects/{project_id}/context")
async def get_shared_context(project_id: str):
    """Return the shared agent context as Markdown.

    Agents read this at session start to understand the project graph
    structure, knowledge sources, recent findings, and the agent roster.
    Stored on disk at ``<project>/.loom/SHARED_CONTEXT.md`` so agents
    can also read it directly from the filesystem.
    """
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from daemon.shared_context import generate_shared_context
    path = await generate_shared_context(
        project_id, project.project_path, graph_engine, registry
    )

    try:
        content = open(path).read()
    except FileNotFoundError:
        content = ""

    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content, media_type="text/markdown")


@app.post("/api/projects/{project_id}/rebuild")
async def rebuild_graph(project_id: str):
    """Build or rebuild the project knowledge graph.

    If the project has at least one online agent, the build is dispatched as
    a tracked task to that agent: the daemon runs graphify in the background
    and marks the task as completed when the build finishes.  The task (and
    its status) appear in the project's dispatch history.

    When no agent is online the daemon runs the build synchronously (direct
    mode) and returns the result immediately — no task is created.
    """
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Find the first online agent to "own" this build.
    agents = await registry.list_agents(project_id)
    online_agent = next(
        (a for a in agents if a.status == AgentStatus.ONLINE), None
    )

    if online_agent is None:
        # --- Direct mode (no agent available) ---
        result = await graph_engine.build_project(project.project_path)
        communities = 0
        if result.status == "completed":
            stats = await graph_engine.get_stats(project.project_path)
            communities = stats.communities
            await registry.update_graph_stats(
                project_id, result.nodes, result.edges, communities
            )
        if router:
            await router._emit_event("graph:updated", project_id, {
                "nodes_added": result.nodes,
                "edges_added": result.edges,
                "communities": communities,
                "status": result.status,
                "error": result.error,
            })
        # Best-effort knowledge scan
        try:
            from daemon.project_knowledge import ingest_all_sources
            await ingest_all_sources(project_id, project.project_path)
        except Exception:
            pass
        return {**result.model_dump(), "mode": "direct"}

    # --- Agent-driven mode ---
    task_id = str(uuid.uuid4())
    instruction = (
        f"Build the knowledge graph for this project by running: "
        f"graphify {project.project_path}"
    )

    # Dual-write: inbox file (so the agent can see it) + registry row.
    inbox_dir = os.path.expanduser(f"~/.loom/inbox/{project_id}")
    os.makedirs(inbox_dir, exist_ok=True)
    task_payload = TaskPayload(
        task_id=task_id,
        target_agent=online_agent.agent_name,
        instruction=instruction,
        priority="high",
    )
    with open(os.path.join(inbox_dir, f"task-{task_id}.json"), "w") as f:
        f.write(task_payload.model_dump_json())

    await registry.create_task(
        task_id, project_id, online_agent.agent_name, instruction, "high"
    )

    if router:
        await router._emit_event("agent:dispatched", project_id, {
            "task_id": task_id,
            "target_agent": online_agent.agent_name,
            "instruction": instruction,
        })

    # Kick off the build in the background — the agent "owns" the task
    # but the daemon executes graphify so the build actually happens.
    asyncio.create_task(
        _build_graph_background(project_id, project.project_path, task_id)
    )

    return {
        "task_id": task_id,
        "agent": online_agent.agent_name,
        "status": "building",
        "mode": "agent",
    }


async def _build_graph_background(
    project_id: str, project_path: str, task_id: str
):
    """Run graphify in the background and wire up task + graph events.

    This is the execution half of an agent-dispatched build.  When the
    daemon finishes the build it marks the dispatch task as completed and
    emits ``task:completed`` / ``graph:updated`` so every connected
    dashboard reloads live.
    """
    try:
        result = await graph_engine.build_project(project_path)
        communities = 0

        # build_project swallows graphify errors and returns status="failed"
        # rather than raising — so a failed build must be surfaced here as a
        # failed task, otherwise the dashboard reports "build complete" over an
        # empty graph.
        if result.status != "completed":
            await registry.fail_task(task_id, result.error)
            if router:
                await router._emit_event("task:failed", project_id, {
                    "task_id": task_id,
                    "error": result.error,
                })
            return

        stats = await graph_engine.get_stats(project_path)
        communities = stats.communities
        await registry.update_graph_stats(
            project_id, result.nodes, result.edges, communities
        )

        await registry.complete_task(task_id)

        if router:
            await router._emit_event("task:completed", project_id, {
                "task_id": task_id,
                "status": result.status,
                "nodes": result.nodes,
                "edges": result.edges,
            })
            await router._emit_event("graph:updated", project_id, {
                "nodes_added": result.nodes,
                "edges_added": result.edges,
                "communities": communities,
                "status": result.status,
                "error": result.error,
            })

        # Best-effort knowledge scan
        try:
            from daemon.project_knowledge import ingest_all_sources
            await ingest_all_sources(project_id, project_path)
        except Exception:
            pass

        # Regenerate shared agent context
        try:
            from daemon.shared_context import generate_shared_context
            await generate_shared_context(
                project_id, project_path, graph_engine, registry
            )
        except Exception:
            pass

    except Exception as exc:
        logger.error("Background graph build failed for %s: %s", project_id, exc)
        if router:
            await router._emit_event("task:failed", project_id, {
                "task_id": task_id,
                "error": str(exc),
            })

@app.post("/api/projects", status_code=201)
async def create_project(payload: ProjectCreatePayload):
    """Create a new tracked project."""
    path = os.path.expanduser(payload.path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")
    try:
        project = await registry.create_project(payload.name, payload.name, path)
    except ProjectExistsError:
        raise HTTPException(status_code=409, detail=f"Project '{payload.name}' is already tracked")
    if router:
        await router._emit_event("project:created", payload.name, {
            "project_id": payload.name,
            "project_name": payload.name,
        })
    return project.model_dump()

@app.delete("/api/projects/{project_id}")
async def delete_project(project_id: str):
    """Remove a project from tracking."""
    deleted = await registry.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")
    if router:
        await router._emit_event("project:deleted", project_id, {"project_id": project_id})
    return {"deleted": True}

@app.get("/api/discover")
async def discover_directories(path: str = "~"):
    """Browse filesystem directories for project discovery.

    Does not follow symlinks (so a malicious link can't redirect browsing
    outside the intended tree) and skips dot-directories.
    """
    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        raise HTTPException(status_code=400, detail="Path does not exist")
    dirs = []
    try:
        with os.scandir(expanded) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                # is_dir(follow_symlinks=False) avoids descending into a
                # symlink that points elsewhere on the filesystem.
                if entry.is_dir(follow_symlinks=False):
                    has_git = os.path.isdir(os.path.join(entry.path, ".git"))
                    dirs.append({"name": entry.name, "path": entry.path, "has_git": has_git})
    except PermissionError:
        pass
    dirs.sort(key=lambda d: d["name"])
    return {"directories": dirs, "parent": os.path.dirname(expanded)}

@app.get("/api/projects/{project_id}/snapshots")
async def get_snapshots(project_id: str, agent_id: str = None):
    """Return agent state snapshots for time-travel debugging."""
    if snapshot_manager is None:
        return {"snapshots": []}
    snaps = await snapshot_manager.replay(project=project_id, agent_id=agent_id)
    return {"snapshots": [s.to_dict() for s in snaps]}


@app.get("/api/traces")
async def get_traces(project: str = None, agent_id: str = None, limit: int = 50):
    """Return recent agent execution traces, optionally filtered."""
    if trace_capture is None:
        return {"traces": []}
    spans = await trace_capture.get_spans(
        project=project, agent_id=agent_id, limit=limit
    )
    return {"traces": [s.to_dict() for s in spans]}


@app.get("/api/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "graphify_available": graph_engine.available if graph_engine else False,
        "watcher_running": watcher.is_running if watcher else False,
    }


# ------------------------------------------------------------------
# Agent task board (Kanban — Feature 2)
# ------------------------------------------------------------------

@app.post("/api/projects/{project_id}/tasks", status_code=201)
async def create_agent_task(project_id: str, payload: AgentTaskCreatePayload):
    """Create a new agent coordination task."""
    if payload.project != project_id:
        payload.project = project_id
    task_id = await registry.create_agent_task(payload)
    record = await registry.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=500, detail="Task creation failed")
    if router:
        await router._emit_event("task:created", project_id, record.model_dump())
    return record.model_dump()


@app.get("/api/projects/{project_id}/tasks")
async def list_agent_tasks(project_id: str, status: str = None):
    """List agent tasks for a project, optionally filtered by status."""
    tasks = await registry.list_agent_tasks(project_id, status_filter=status)
    return [t.model_dump() for t in tasks]


@app.patch("/api/projects/{project_id}/tasks/{task_id}")
async def update_agent_task(project_id: str, task_id: str, payload: AgentTaskUpdatePayload):
    """Update an agent task's status, assignee, or result."""
    record = await registry.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    await registry.update_agent_task(
        task_id,
        status=payload.status,
        assignee=payload.assignee,
        result=payload.result,
    )
    updated = await registry.get_agent_task(task_id)
    if updated is None:
        raise HTTPException(status_code=500, detail="Task update failed")
    if router:
        await router._emit_event("task:updated", project_id, updated.model_dump())
    return updated.model_dump()


@app.get("/api/projects/{project_id}/search")
async def hybrid_search(project_id: str, q: str = ""):
    """Hybrid search: text + vector cosine similarity over inbox findings."""
    if not q:
        return {"results": []}
    results = await registry.hybrid_search(project_id, q)
    return {"results": results}


@app.post("/api/projects/{project_id}/eval")
async def run_eval(project_id: str, payload: dict):
    """Run an evaluation against agent output."""
    global eval_engine
    if eval_engine is None:
        from daemon.evals import EvalEngine
        eval_engine = EvalEngine()
    case = await eval_engine.evaluate(
        project=project_id,
        agent_id=payload.get("agent_id", "unknown"),
        criterion=payload.get("criterion", "no_hardcoded_secrets"),
        expected=payload.get("expected", ""),
        actual=payload.get("actual", ""),
    )
    return case.to_dict()


@app.get("/api/projects/{project_id}/eval")
async def get_evals(project_id: str):
    """Return evaluation results for a project."""
    global eval_engine
    if eval_engine is None:
        from daemon.evals import EvalEngine
        eval_engine = EvalEngine()
    results = await eval_engine.get_results(project=project_id)
    return {"evals": [r.to_dict() for r in results]}


@app.get("/api/projects/{project_id}/eval/pass-rate")
async def get_eval_pass_rate(project_id: str):
    """Return pass/warn/fail rates for a project."""
    global eval_engine
    if eval_engine is None:
        from daemon.evals import EvalEngine
        eval_engine = EvalEngine()
    return await eval_engine.get_pass_rate(project=project_id)


@app.get("/api/patterns")
async def list_patterns(project: str = None, status: str = None):
    """Return evolved patterns, optionally filtered."""
    global pattern_repo
    if pattern_repo is None:
        from daemon.patterns import PatternRepository, PatternStatus
        pattern_repo = PatternRepository()
    if status:
        try:
            ps = PatternStatus(status)
        except ValueError:
            ps = None
    else:
        ps = None
    patterns = await pattern_repo.list_patterns(project=project, status=ps)
    return {"patterns": [p.to_dict() for p in patterns]}


@app.get("/api/patterns/top")
async def top_patterns(limit: int = 10):
    """Return highest-confidence patterns."""
    global pattern_repo
    if pattern_repo is None:
        from daemon.patterns import PatternRepository
        pattern_repo = PatternRepository()
    patterns = await pattern_repo.top_patterns(limit=limit)
    return {"patterns": [p.to_dict() for p in patterns]}


@app.get("/api/patterns/cross-project")
async def cross_project_patterns():
    """Return patterns seen across multiple projects."""
    global pattern_repo
    if pattern_repo is None:
        from daemon.patterns import PatternRepository
        pattern_repo = PatternRepository()
    patterns = await pattern_repo.cross_project_patterns()
    return {"patterns": [p.to_dict() for p in patterns]}


@app.post("/api/projects/{project_id}/patterns/observe")
async def observe_pattern(project_id: str, payload: dict):
    """Record a pattern observation from an agent."""
    global pattern_repo
    if pattern_repo is None:
        from daemon.patterns import PatternRepository
        pattern_repo = PatternRepository()
    pattern = await pattern_repo.observe(
        pattern_text=payload.get("pattern_text", ""),
        project=project_id,
        agent_id=payload.get("agent_id", "unknown"),
        kind=payload.get("kind", "PATTERN"),
    )
    return pattern.to_dict()


@app.patch("/api/patterns/{pattern_id}/deprecate")
async def deprecate_pattern(pattern_id: str, payload: dict = None):
    """Mark a pattern as deprecated."""
    global pattern_repo
    if pattern_repo is None:
        from daemon.patterns import PatternRepository
        pattern_repo = PatternRepository()
    p = await pattern_repo.deprecate(pattern_id, reason=(payload or {}).get("reason", ""))
    if p is None:
        raise HTTPException(status_code=404, detail="Pattern not found")
    return p.to_dict()


@app.get("/api/projects/{project_id}/audit")
async def get_audit_log(project_id: str, agent_id: str = None, action: str = None, limit: int = 100):
    """Return audit events for a project, optionally filtered."""
    global audit_trail
    if audit_trail is None:
        from daemon.audit import AuditTrail
        audit_trail = AuditTrail()
        await audit_trail.initialize()
    events = await audit_trail.query(
        project=project_id, agent_id=agent_id, action=action, limit=limit,
    )
    return {"events": events}


@app.get("/api/projects/{project_id}/audit/summary")
async def get_audit_summary(project_id: str):
    """Return daily audit summary for a project."""
    global audit_trail
    if audit_trail is None:
        from daemon.audit import AuditTrail
        audit_trail = AuditTrail()
        await audit_trail.initialize()
    return {"summary": await audit_trail.summary(project=project_id)}


# --- Temporal facts ---

@app.post("/api/projects/{project_id}/facts")
async def record_fact(project_id: str, payload: dict):
    """Record a temporal fact."""
    global temporal_tracker
    if temporal_tracker is None:
        from daemon.temporal import TemporalTracker
        temporal_tracker = TemporalTracker()
    fact = await temporal_tracker.record(
        fact_text=payload.get("fact_text", ""),
        project=project_id,
        agent_id=payload.get("agent_id", "unknown"),
    )
    return fact.to_dict()


@app.get("/api/projects/{project_id}/facts")
async def list_facts(project_id: str, active_only: bool = True):
    """List temporal facts for a project."""
    global temporal_tracker
    if temporal_tracker is None:
        from daemon.temporal import TemporalTracker
        temporal_tracker = TemporalTracker()
    facts = (
        await temporal_tracker.active_facts(project=project_id)
        if active_only
        else await temporal_tracker.list_facts(project=project_id)
    )
    return {"facts": [f.to_dict() for f in facts]}


@app.get("/api/projects/{project_id}/facts/timeline")
async def facts_timeline(project_id: str):
    """Return facts in chronological order."""
    global temporal_tracker
    if temporal_tracker is None:
        from daemon.temporal import TemporalTracker
        temporal_tracker = TemporalTracker()
    facts = await temporal_tracker.timeline(project=project_id)
    return {"facts": [f.to_dict() for f in facts]}


@app.patch("/api/facts/{fact_id}/expire")
async def expire_fact(fact_id: str, payload: dict = None):
    """Expire a temporal fact."""
    global temporal_tracker
    if temporal_tracker is None:
        from daemon.temporal import TemporalTracker
        temporal_tracker = TemporalTracker()
    fact = await temporal_tracker.expire(
        fact_id, reason=(payload or {}).get("reason", "")
    )
    if fact is None:
        raise HTTPException(status_code=404, detail="Fact not found")
    return fact.to_dict()


# --- Document ingestion ---

@app.post("/api/projects/{project_id}/ingest")
async def ingest_document(project_id: str, payload: dict):
    """Ingest a document into the project knowledge base."""
    global doc_ingestor
    if doc_ingestor is None:
        from daemon.ingest import DocumentIngestor
        doc_ingestor = DocumentIngestor()
    result = await doc_ingestor.ingest_file(
        file_path=payload.get("file_path", ""),
        project=project_id,
        agent_id=payload.get("agent_id", "ingestor"),
    )
    return result


@app.post("/api/projects/{project_id}/ingest/directory")
async def ingest_directory(project_id: str, payload: dict):
    """Ingest all files in a directory."""
    global doc_ingestor
    if doc_ingestor is None:
        from daemon.ingest import DocumentIngestor
        doc_ingestor = DocumentIngestor()
    results = await doc_ingestor.ingest_directory(
        dir_path=payload.get("dir_path", ""),
        project=project_id,
        agent_id=payload.get("agent_id", "ingestor"),
    )
    return {"results": results}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket for live event streaming."""
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connected_clients.remove(websocket)


async def _broadcast_events():
    """Broadcast router events to all connected WebSocket clients."""
    if router is None:
        # Defensive: the lifespan only starts this task outside test mode,
        # where router is always set. Guard anyway so a future code path
        # can't AttributeError the startup.
        return
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
