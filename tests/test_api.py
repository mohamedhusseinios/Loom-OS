"""Tests for the FastAPI application.

These cover the API error-handling paths that previously returned a
tuple (Flask-ism) instead of setting the HTTP status code, plus the
happy paths for the project/project-detail/health endpoints.

The app is driven with Starlette/FastAPI TestClient. The real ``lifespan``
is suppressed (``lifespan="off"``) so tests don't start a filesystem
watcher, a broadcast task, or touch ``~/.loom``. Instead we inject
a temp-backed registry and graph engine into the module-level globals the
route handlers read.
"""
import pytest
from fastapi.testclient import TestClient

import daemon.api as api_module
from daemon.graph_engine import GraphEngine
from daemon.models import AgentInfo
from daemon.registry import AgentRegistry


@pytest.fixture
async def client(tmp_path):
    """Yield a TestClient wired to a temp registry + graph engine."""
    registry = AgentRegistry(str(tmp_path / "test.db"))
    await registry.initialize()

    # Seed one project + one agent so the detail/agents endpoints have data.
    await registry.upsert_project("noor", str(tmp_path / "noor"))
    await registry.upsert_agent(
        AgentInfo(
            agent_id="claude-code-noor",
            agent_name="claude-code",
            version="1.0",
            project="noor",
            capabilities=["code-analysis"],
        )
    )

    # Inject into the module globals the handlers use.
    api_module.registry = registry
    api_module.graph_engine = GraphEngine()
    api_module.router = None
    api_module.watcher = None

    # lifespan="off" skips startup/shutdown (no watcher/broadcast task).
    with TestClient(api_module.app) as c:
        yield c

    await registry.close()


def test_list_projects(client):
    """Projects seeded by the fixture are listed."""
    res = client.get("/api/projects")
    assert res.status_code == 200
    data = res.json()
    assert "projects" in data
    ids = [p["project_id"] for p in data["projects"]]
    assert "noor" in ids


def test_get_project(client):
    """Existing project returns 200 with project/graph/agents keys."""
    res = client.get("/api/projects/noor")
    assert res.status_code == 200
    data = res.json()
    assert data["project"]["project_id"] == "noor"
    assert "graph" in data
    assert len(data["agents"]) == 1
    assert data["agents"][0]["agent_name"] == "claude-code"


def test_get_project_not_found_returns_404(client):
    """Regression: must return HTTP 404, not 200 with a tuple body."""
    res = client.get("/api/projects/does-not-exist")
    assert res.status_code == 404
    # Body is FastAPI's default {"detail": "..."} error envelope.
    assert "detail" in res.json()


def test_get_graph_stats_not_found_returns_404(client):
    res = client.get("/api/projects/missing/graph")
    assert res.status_code == 404


def test_query_missing_q_returns_400(client):
    """Regression: must return HTTP 400, not 200 with a tuple body."""
    res = client.get("/api/projects/noor/query")
    assert res.status_code == 400
    assert "detail" in res.json()


def test_query_project_not_found_returns_404(client):
    res = client.get("/api/projects/missing/query?q=hello")
    assert res.status_code == 404


def test_list_agents(client):
    res = client.get("/api/projects/noor/agents")
    assert res.status_code == 200
    data = res.json()
    assert len(data["agents"]) == 1
    assert data["agents"][0]["agent_name"] == "claude-code"


def test_list_agents_unknown_project_empty(client):
    # No 404 for agents endpoint by design — just an empty list.
    res = client.get("/api/projects/unknown/agents")
    assert res.status_code == 200
    assert res.json()["agents"] == []


def test_rebuild_project_not_found_returns_404(client):
    res = client.post("/api/projects/missing/rebuild")
    assert res.status_code == 404


def test_health(client):
    """Health endpoint reports graphify availability from the injected engine."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "graphify_available" in data
    assert "watcher_running" in data

def test_create_project(client):
    """POST /api/projects creates a new tracked project."""
    res = client.post("/api/projects", json={"name": "test-proj", "path": "/tmp"})
    assert res.status_code == 201
    data = res.json()
    assert data["project_id"] == "test-proj"

def test_create_project_invalid_path(client):
    """POST /api/projects with non-existent path returns 400."""
    res = client.post("/api/projects", json={"name": "bad", "path": "/nonexistent/path"})
    assert res.status_code == 400

def test_delete_project(client):
    """DELETE /api/projects/:id removes a project."""
    client.post("/api/projects", json={"name": "del-me", "path": "/tmp"})
    res = client.delete("/api/projects/del-me")
    assert res.status_code == 200
    assert res.json()["deleted"] is True

def test_delete_project_not_found(client):
    """DELETE /api/projects/:id with unknown id returns 404."""
    res = client.delete("/api/projects/nonexistent")
    assert res.status_code == 404

def test_discover_directories(client):
    """GET /api/discover returns subdirectories."""
    res = client.get("/api/discover?path=/tmp")
    assert res.status_code == 200
    data = res.json()
    assert "directories" in data
    assert "parent" in data

def test_discover_invalid_path(client):
    """GET /api/discover with invalid path returns 400."""
    res = client.get("/api/discover?path=/nonexistent")
    assert res.status_code == 400

def test_get_graph_topology_404(client):
    """Graph topology for unknown project returns 404."""
    res = client.get("/api/projects/nonexistent/graph/topology")
    assert res.status_code == 404

def test_get_graph_communities_404(client):
    """Graph communities for unknown project returns 404."""
    res = client.get("/api/projects/nonexistent/graph/communities")
    assert res.status_code == 404


def test_create_project_duplicate_returns_409(client):
    """Re-creating an already-tracked project returns 409, not 500."""
    client.post("/api/projects", json={"name": "dupe", "path": "/tmp"})
    res = client.post("/api/projects", json={"name": "dupe", "path": "/tmp"})
    assert res.status_code == 409
    assert "detail" in res.json()


def test_dispatch_task(client):
    """POST /dispatch persists a task and returns its id."""
    res = client.post(
        "/api/projects/noor/dispatch",
        json={"target_agent": "claude-code", "instruction": "review auth", "priority": "high"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "dispatched"
    assert "task_id" in data


def test_dispatch_task_unknown_project_404(client):
    res = client.post(
        "/api/projects/missing/dispatch",
        json={"target_agent": "claude-code", "instruction": "x"},
    )
    assert res.status_code == 404


def test_list_dispatches(client):
    """GET /dispatches returns tasks created via the dispatch endpoint."""
    client.post(
        "/api/projects/noor/dispatch",
        json={"target_agent": "claude-code", "instruction": "do A"},
    )
    client.post(
        "/api/projects/noor/dispatch",
        json={"target_agent": "claude-code", "instruction": "do B"},
    )
    res = client.get("/api/projects/noor/dispatches")
    assert res.status_code == 200
    dispatches = res.json()["dispatches"]
    assert len(dispatches) == 2
    # Ordered newest-first (dispatched_at DESC).
    instructions = [d["instruction"] for d in dispatches]
    assert instructions == ["do B", "do A"]


def test_agent_task_lifecycle_api(client):
    """Full lifecycle: POST → GET → PATCH → verify."""
    # Create
    res = client.post(
        "/api/projects/noor/tasks",
        json={"project": "noor", "title": "Fix auth", "instruction": "do it", "priority": 1},
    )
    assert res.status_code == 201
    task = res.json()
    assert task["status"] == "todo"
    task_id = task["id"]

    # List
    res = client.get("/api/projects/noor/tasks")
    assert res.status_code == 200
    tasks = res.json()
    assert any(t["id"] == task_id for t in tasks)

    # Update status
    res = client.patch(
        f"/api/projects/noor/tasks/{task_id}",
        json={"status": "running", "assignee": "agent-1"},
    )
    assert res.status_code == 200
    updated = res.json()
    assert updated["status"] == "running"
    assert updated["assignee"] == "agent-1"


def test_agent_task_list_unknown_project_empty(client):
    """Listing tasks for unknown project returns empty list."""
    res = client.get("/api/projects/unknown/tasks")
    assert res.status_code == 200
    assert res.json() == []


def test_agent_task_update_not_found_returns_404(client):
    """PATCH of unknown task returns 404."""
    res = client.patch(
        "/api/projects/noor/tasks/nonexistent",
        json={"status": "done"},
    )
    assert res.status_code == 404


def test_full_task_lifecycle_with_dependencies(client):
    """End-to-end: parent blocks child until parent completes."""
    pid = "noor"

    # Create parent task
    res = client.post(
        f"/api/projects/{pid}/tasks",
        json={"project": pid, "title": "Setup DB", "instruction": "init", "priority": 1},
    )
    assert res.status_code == 201
    parent_id = res.json()["id"]

    # Create child task dependent on parent
    res = client.post(
        f"/api/projects/{pid}/tasks",
        json={
            "project": pid,
            "title": "Run Migrations",
            "instruction": "migrate",
            "dependencies": [parent_id],
            "priority": 1,
        },
    )
    assert res.status_code == 201
    child = res.json()
    assert child["status"] == "todo"  # parent not done yet

    # Complete parent
    res = client.patch(
        f"/api/projects/{pid}/tasks/{parent_id}",
        json={"status": "done"},
    )
    assert res.status_code == 200

    # Now create another child — should auto-promote to ready
    res = client.post(
        f"/api/projects/{pid}/tasks",
        json={
            "project": pid,
            "title": "Seed Data",
            "instruction": "seed",
            "dependencies": [parent_id],
            "priority": 1,
        },
    )
    assert res.status_code == 201
    child2 = res.json()
    assert child2["status"] == "ready"  # parent is DONE

    # Assign and run the child task
    res = client.patch(
        f"/api/projects/{pid}/tasks/{child2["id"]}",
        json={"status": "running", "assignee": "agent-1"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "running"

    # Complete child
    res = client.patch(
        f"/api/projects/{pid}/tasks/{child2["id"]}",
        json={"status": "done"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "done"

    # Verify all tasks are listed
    res = client.get(f"/api/projects/{pid}/tasks")
    assert res.status_code == 200
    all_tasks = res.json()
    task_ids = {t["id"] for t in all_tasks}
    assert parent_id in task_ids
    assert child["id"] in task_ids
    assert child2["id"] in task_ids


def test_hybrid_search_returns_empty_on_no_query(client):
    """Search with no query returns empty results."""
    res = client.get("/api/projects/noor/search")
    assert res.status_code == 200
    assert res.json()["results"] == []


def test_hybrid_search_accepts_query(client):
    """Search with a query returns results structure."""
    res = client.get("/api/projects/noor/search?q=authentication")
    assert res.status_code == 200
    data = res.json()
    assert "results" in data
    assert isinstance(data["results"], list)


def test_get_traces_returns_empty(client):
    """GET /api/traces returns empty when no traces exist."""
    res = client.get("/api/traces")
    assert res.status_code == 200
    assert res.json()["traces"] == []


def test_run_eval(client):
    """POST /eval scores agent output."""
    res = client.post(
        "/api/projects/noor/eval",
        json={
            "agent_id": "claude-code",
            "criterion": "no_todos",
            "expected": "No TODOs",
            "actual": "def foo(): return 42",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["score"] == "pass"


def test_get_evals(client):
    """GET /eval returns eval results."""
    # Seed one eval
    client.post(
        "/api/projects/noor/eval",
        json={
            "agent_id": "claude-code",
            "criterion": "no_todos",
            "expected": "x",
            "actual": "clean",
        },
    )
    res = client.get("/api/projects/noor/eval")
    assert res.status_code == 200
    assert len(res.json()["evals"]) >= 1


def test_get_eval_pass_rate(client):
    """GET /eval/pass-rate returns statistics."""
    client.post(
        "/api/projects/noor/eval",
        json={
            "agent_id": "claude-code",
            "criterion": "no_todos",
            "expected": "x",
            "actual": "clean",
        },
    )
    res = client.get("/api/projects/noor/eval/pass-rate")
    assert res.status_code == 200
    data = res.json()
    assert "pass" in data
    assert "total" in data
    assert "pass_rate" in data


def test_get_snapshots_returns_empty(client):
    """GET /snapshots returns empty list when no snapshots exist."""
    res = client.get("/api/projects/noor/snapshots")
    assert res.status_code == 200
    assert res.json()["snapshots"] == []


def test_task_create_and_update_emit_ws_events(client):
    """POST emits task:created, PATCH emits task:updated (router injected)."""
    from daemon.router import Router
    import daemon.api as api_module

    api_module.router = Router(api_module.registry, api_module.graph_engine)
    try:
        res = client.post(
            "/api/projects/noor/tasks",
            json={"project": "noor", "title": "T", "instruction": "do", "priority": 0},
        )
        assert res.status_code == 201
        task_id = res.json()["id"]

        created = api_module.router.events.get_nowait()
        assert created.event == "task:created"
        assert created.data["id"] == task_id

        res = client.patch(
            f"/api/projects/noor/tasks/{task_id}",
            json={"status": "running", "assignee": "claude-code-noor"},
        )
        assert res.status_code == 200
        updated = api_module.router.events.get_nowait()
        assert updated.event == "task:updated"
        assert updated.data["status"] == "running"
    finally:
        api_module.router = None  # always reset, even on failure


def test_dependency_repromotion_on_parent_done(client):
    """A todo child auto-promotes to ready when its parent is marked done,
    and a task:updated event is emitted for the promoted child."""
    from daemon.router import Router
    import daemon.api as api_module

    res = client.post("/api/projects/noor/tasks",
                      json={"project": "noor", "title": "Parent", "instruction": "x"})
    parent_id = res.json()["id"]
    res = client.post("/api/projects/noor/tasks",
                      json={"project": "noor", "title": "Child", "instruction": "y",
                            "dependencies": [parent_id]})
    child_id = res.json()["id"]
    assert res.json()["status"] == "todo"

    api_module.router = Router(api_module.registry, api_module.graph_engine)
    try:
        client.patch(f"/api/projects/noor/tasks/{parent_id}", json={"status": "done"})

        events = []
        while not api_module.router.events.empty():
            events.append(api_module.router.events.get_nowait())
        promoted = [e for e in events
                    if e.event == "task:updated"
                    and e.data["id"] == child_id
                    and e.data["status"] == "ready"]
        assert promoted, "expected a task:updated(ready) event for the promoted child"
    finally:
        api_module.router = None

    res = client.get("/api/projects/noor/tasks")
    child = next(t for t in res.json() if t["id"] == child_id)
    assert child["status"] == "ready"


def test_task_progress_endpoint_emits_event(client):
    from daemon.router import Router
    import daemon.api as api_module
    api_module.router = Router(api_module.registry, api_module.graph_engine)
    try:
        res = client.post(
            "/api/projects/noor/tasks",
            json={"project": "noor", "title": "T", "instruction": "do"},
        )
        task_id = res.json()["id"]
        api_module.router.events.get_nowait()  # drain task:created

        res = client.post(
            f"/api/projects/noor/tasks/{task_id}/progress",
            json={"message": "running tool: Edit"},
        )
        assert res.status_code == 200
        ev = api_module.router.events.get_nowait()
        assert ev.event == "task:progress"
        assert ev.data == {"id": task_id, "message": "running tool: Edit"}
    finally:
        api_module.router = None


def test_update_persists_workspace_path(client):
    res = client.post(
        "/api/projects/noor/tasks",
        json={"project": "noor", "title": "T", "instruction": "do"},
    )
    task_id = res.json()["id"]
    res = client.patch(
        f"/api/projects/noor/tasks/{task_id}",
        json={"workspace_path": "/tmp/ws/task-1"},
    )
    assert res.status_code == 200
    assert res.json()["workspace_path"] == "/tmp/ws/task-1"


def test_task_diff_empty_without_workspace(client):
    res = client.post(
        "/api/projects/noor/tasks",
        json={"project": "noor", "title": "T", "instruction": "do"},
    )
    task_id = res.json()["id"]
    res = client.get(f"/api/projects/noor/tasks/{task_id}/diff")
    assert res.status_code == 200
    assert res.json() == {"diff": "", "branch": f"loom/task-{task_id}"}


def test_task_diff_404_for_unknown_task(client):
    res = client.get("/api/projects/noor/tasks/nope/diff")
    assert res.status_code == 404
