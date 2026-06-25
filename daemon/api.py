"""FastAPI application for the Agentic OS daemon."""

from typing import Optional

import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from daemon.registry import AgentRegistry
from daemon.graph_engine import GraphEngine
from daemon.router import Router
from daemon.watcher import InboxWatcher
from daemon.models import WsEvent, ProjectCreatePayload, DispatchRequest, TaskPayload

logger = logging.getLogger(__name__)

# Global state
registry: Optional[AgentRegistry] = None
graph_engine: Optional[GraphEngine] = None
router: Optional[Router] = None
watcher: Optional[InboxWatcher] = None
connected_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start watcher on startup, clean up on shutdown.

    Honors globals pre-set by tests: if a registry/graph_engine has been
    injected, the lifespan reuses it and skips the filesystem watcher /
    broadcast task (which depend on real ``~/.agentic-os`` state).
    """
    global registry, graph_engine, router, watcher

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

    if not test_mode:
        watcher = InboxWatcher()
        loop = asyncio.get_running_loop()
        watcher.start(router.handle_file, loop)
        # Background task: broadcast events to WebSocket clients
        asyncio.create_task(_broadcast_events())

    logger.info("Agentic OS daemon started")
    yield
    if watcher is not None:
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
    """Dispatch a task to an agent."""
    import uuid, os
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

    inbox_dir = os.path.expanduser(f"~/.agentic-os/inbox/{project_id}")
    os.makedirs(inbox_dir, exist_ok=True)
    task_path = os.path.join(inbox_dir, f"task-{task_id}.json")
    with open(task_path, "w") as f:
        f.write(task_payload.model_dump_json())

    await registry.create_task(task_id, project_id, payload.target_agent, payload.instruction, payload.priority)

    if router:
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
        raise HTTPException(status_code=404, detail="Project not found")
    result = await graph_engine.build_project(project.project_path)
    return result.model_dump()

@app.post("/api/projects", status_code=201)
async def create_project(payload: ProjectCreatePayload):
    """Create a new tracked project."""
    import os
    path = os.path.expanduser(payload.path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Path does not exist or is not a directory")
    project = await registry.create_project(payload.name, payload.name, path)
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
    """Browse filesystem directories for project discovery."""
    import os
    expanded = os.path.expanduser(path)
    if not os.path.isdir(expanded):
        raise HTTPException(status_code=400, detail="Path does not exist")
    dirs = []
    try:
        for entry in sorted(os.listdir(expanded)):
            full = os.path.join(expanded, entry)
            if os.path.isdir(full) and not entry.startswith("."):
                has_git = os.path.isdir(os.path.join(full, ".git"))
                dirs.append({"name": entry, "path": full, "has_git": has_git})
    except PermissionError:
        pass
    return {"directories": dirs, "parent": os.path.dirname(expanded)}

@app.get("/api/health")
async def health():
    """Health check."""
    return {
        "status": "ok",
        "graphify_available": graph_engine.available if graph_engine else False,
        "watcher_running": watcher.is_running if watcher else False,
    }


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
