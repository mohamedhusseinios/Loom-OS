# Kanban Task Board + Autonomous Claude Code Worker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an interactive Kanban board to the Loom OS dashboard for adding/assigning/managing agent tasks, plus a `loom worker` process that autonomously runs Claude Code (headless) in an isolated git worktree when a task is moved to Running.

**Architecture:** The `agent_tasks` coordination backend (7-state model, SQLite table, CRUD API, dependency auto-promotion) already exists. This plan adds (A) daemon WebSocket events + dependency re-promotion + worktree diff/merge endpoints, (B) a first-party `loom worker` that polls the HTTP API, creates a git worktree, runs `claude -p`, and writes results + findings back, and (C) the dashboard Kanban UI. The daemon stays single-process and credential-free; the worker is the only new process and talks to the daemon over its existing REST API.

**Tech Stack:** Python 3.11+ (FastAPI, aiosqlite, stdlib `subprocess`/`urllib`), Claude Code headless CLI (`claude -p`), git worktrees, TypeScript (Next.js 16.2, React 19.2, next-intl 4, Tailwind v4), native HTML5 drag-and-drop.

## Global Constraints

- **Existing test suite stays green** — run `pytest tests/ -v` after each daemon task; do not break the current passing tests.
- **No new infrastructure** — no Docker, Neo4j, or external DB. `git` and `claude` are invoked as subprocesses. **No new Python dependencies** (worker uses stdlib `urllib`/`subprocess`/`json`). **No new dashboard dependencies** (native HTML5 drag-and-drop, native `<dialog>`).
- **Single-process daemon preserved** — the daemon never spawns agents or holds credentials. `loom worker` is a separate, optional process the user runs.
- **Filesystem moat preserved** — third-party agents still talk only via the inbox. The worker is first-party Loom code and may use the daemon's HTTP API; its task results are also auto-retained as `finding-*.md` in the inbox.
- **Per-project isolation** — tasks, worktrees, and worker identities are all project-scoped.
- **Daemon globals pattern** — route handlers read module-level globals (`registry`, `router`). Emit WS events with `if router: await router._emit_event(event, project, data)` (matches `dispatch_task`). Tests set `api_module.router = None`, so WS-emission tests must inject a `Router` (see Task A1).
- **Dashboard pages are client components** using `useParams<{ id: string }>()` and `useTranslations(...)`; mirror `dashboard/app/[locale]/projects/[id]/graph/page.tsx`. Modals use the native `<dialog>` element; mirror `dashboard/components/dispatch-modal.tsx`. **Before writing dashboard code, read the relevant guide in `dashboard/node_modules/next/dist/docs/`** (per `dashboard/AGENTS.md`).
- **i18n** — every user-facing string added to **both** `dashboard/messages/en.json` and `dashboard/messages/ar.json`.
- **Claude Code headless flags/output schema** — the exact `claude -p` flags and `stream-json` event shapes are **verified against the official Claude Code docs at implementation time** (Task B3). Use the `claude-code-guide` agent or the `claude-code`/`claude-api` skills.

## Branch

Work happens on `feat/kanban-task-board` (already created; the design spec is committed there).

## File Structure

**New files**
| File | Responsibility |
|------|----------------|
| `daemon/worktree.py` | Pure git-worktree helpers (create / commit / diff / merge / remove / current-branch). Sync; callers wrap in `asyncio.to_thread`. |
| `daemon/worker.py` | `Worker` class: poll → claim → worktree → `claude -p` → parse → status + findings. Injectable I/O for tests. |
| `tests/test_worktree.py` | Worktree helpers against a real temp git repo. |
| `tests/test_worker.py` | `Worker.process_task` logic with claude/git/HTTP mocked. |
| `dashboard/components/task-board.tsx` | Kanban columns + cards + native drag-and-drop. |
| `dashboard/components/new-task-modal.tsx` | Create-task dialog (native `<dialog>`). |
| `dashboard/components/task-detail-drawer.tsx` | Task detail: result, diff, merge, status/assignee actions. |
| `dashboard/app/[locale]/projects/[id]/tasks/page.tsx` | Tasks route: loads tasks, subscribes to WS, renders the board. |

**Modified files**
| File | Change |
|------|--------|
| `daemon/models.py` | Add `workspace_path` to `AgentTaskUpdatePayload`. |
| `daemon/registry.py` | `update_agent_task` accepts `workspace_path`; add `promote_ready_dependents`. |
| `daemon/api.py` | Emit `task:created`/`task:updated` on task endpoints; add `progress`, `diff`, `merge` endpoints; call re-promotion on `done`. |
| `daemon/main.py` | Add `worker` subcommand (+ `KNOWN_SUBCOMMANDS`). |
| `tests/test_api.py` | Assertions for WS events, re-promotion, progress endpoint. |
| `dashboard/lib/api.ts` | `AgentTask` type + `listAgentTasks`/`createAgentTask`/`updateAgentTask`/`getTaskDiff`/`mergeTask`. |
| `dashboard/messages/en.json`, `dashboard/messages/ar.json` | `TaskBoard` / `NewTaskModal` / `TaskDetail` strings. |
| `dashboard/app/[locale]/projects/[id]/...` (nav) | "Tasks" link beside the existing "Graph" link. |
| `README.md` | Document `loom worker` + the Tasks board. |

---

## Phase 0 — Worktree helpers (`daemon/worktree.py`)

Shared foundation: the worker creates worktrees; the API diffs/merges them. Pure functions over `git` subprocess, synchronous (callers use `asyncio.to_thread`).

### Task 0.1: Git worktree helper module

**Files:**
- Create: `daemon/worktree.py`
- Test: `tests/test_worktree.py`

**Interfaces:**
- Produces:
  - `create_worktree(repo_path: str, workspace_path: str, branch: str, base_ref: str = "HEAD") -> None`
  - `commit_all(workspace_path: str, message: str) -> bool` (True if a commit was created; False if nothing to commit)
  - `current_branch(repo_path: str) -> str`
  - `branch_diff(repo_path: str, base_branch: str, branch: str) -> str` (`git diff base...branch`)
  - `merge_branch(repo_path: str, branch: str) -> tuple[bool, str]` (success, combined output)
  - `remove_worktree(repo_path: str, workspace_path: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worktree.py
import subprocess
from pathlib import Path

import pytest

from daemon import worktree


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def repo(tmp_path):
    """A git repo on branch 'main' with one commit."""
    r = tmp_path / "proj"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@t.test")
    _git(r, "config", "user.name", "t")
    (r / "README.md").write_text("hello\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    return r


def test_create_commit_diff_merge_roundtrip(repo, tmp_path):
    ws = tmp_path / "ws" / "task-abc"
    worktree.create_worktree(str(repo), str(ws), "loom/task-abc", base_ref="main")
    assert ws.exists()
    assert worktree.current_branch(str(repo)) == "main"

    # Agent edits a file in the worktree.
    (ws / "new.txt").write_text("agent work\n")
    made = worktree.commit_all(str(ws), "loom task abc")
    assert made is True

    diff = worktree.branch_diff(str(repo), "main", "loom/task-abc")
    assert "new.txt" in diff
    assert "agent work" in diff

    ok, _out = worktree.merge_branch(str(repo), "loom/task-abc")
    assert ok is True
    assert (repo / "new.txt").read_text() == "agent work\n"

    worktree.remove_worktree(str(repo), str(ws))
    assert not ws.exists()


def test_commit_all_returns_false_when_no_changes(repo, tmp_path):
    ws = tmp_path / "ws" / "task-empty"
    worktree.create_worktree(str(repo), str(ws), "loom/task-empty", base_ref="main")
    assert worktree.commit_all(str(ws), "noop") is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_worktree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.worktree'`

- [ ] **Step 3: Write the implementation**

```python
# daemon/worktree.py
"""Git worktree helpers for isolated, autonomous task execution.

Each running task gets its own worktree + branch so an agent can edit
freely without touching the user's main checkout. Synchronous subprocess
calls — async callers should wrap these in ``asyncio.to_thread``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(cwd: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", cwd, *args],
        capture_output=True, text=True,
    )


def create_worktree(repo_path: str, workspace_path: str, branch: str, base_ref: str = "HEAD") -> None:
    """Create a new worktree at ``workspace_path`` on a fresh ``branch``."""
    Path(workspace_path).parent.mkdir(parents=True, exist_ok=True)
    proc = _run(repo_path, "worktree", "add", "-b", branch, workspace_path, base_ref)
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {proc.stderr.strip()}")


def current_branch(repo_path: str) -> str:
    proc = _run(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def commit_all(workspace_path: str, message: str) -> bool:
    """Stage and commit everything in the worktree. Returns False if clean."""
    _run(workspace_path, "add", "-A")
    status = _run(workspace_path, "status", "--porcelain")
    if not status.stdout.strip():
        return False
    proc = _run(workspace_path, "commit", "-m", message)
    if proc.returncode != 0:
        raise RuntimeError(f"git commit failed: {proc.stderr.strip()}")
    return True


def branch_diff(repo_path: str, base_branch: str, branch: str) -> str:
    """Three-dot diff: changes on ``branch`` since it diverged from base."""
    proc = _run(repo_path, "diff", f"{base_branch}...{branch}")
    if proc.returncode != 0:
        raise RuntimeError(f"git diff failed: {proc.stderr.strip()}")
    return proc.stdout


def merge_branch(repo_path: str, branch: str) -> tuple[bool, str]:
    """Merge ``branch`` into the repo's current branch (no fast-forward)."""
    proc = _run(repo_path, "merge", "--no-ff", "-m", f"Merge {branch}", branch)
    out = (proc.stdout + proc.stderr).strip()
    return proc.returncode == 0, out


def remove_worktree(repo_path: str, workspace_path: str) -> None:
    _run(repo_path, "worktree", "remove", "--force", workspace_path)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_worktree.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add daemon/worktree.py tests/test_worktree.py
git commit -m "feat(daemon): git worktree helpers for isolated task execution"
```

---

## Phase A — Daemon: events, re-promotion, worktree endpoints

### Task A1: Emit `task:created` / `task:updated` WebSocket events

**Files:**
- Modify: `daemon/api.py` (task endpoints at lines ~610–644)
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `router._emit_event(event: str, project: str, data: dict)` (existing).
- Produces: WS events `task:created` (data = task record dict) and `task:updated` (data = task record dict) on the existing task endpoints.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
def test_task_create_and_update_emit_ws_events(client):
    """POST emits task:created, PATCH emits task:updated (router injected)."""
    from daemon.router import Router
    import daemon.api as api_module

    # The fixture sets router=None; inject a real Router so endpoints emit.
    api_module.router = Router(api_module.registry, api_module.graph_engine)

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

    api_module.router = None  # reset for other tests
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_api.py::test_task_create_and_update_emit_ws_events -v`
Expected: FAIL — `QueueEmpty` (no event emitted yet)

- [ ] **Step 3: Add emission to the endpoints**

In `daemon/api.py`, update the two handlers (keep existing bodies; add the `if router:` emit before returning):

```python
# create_agent_task — after `record = await registry.get_agent_task(task_id)` block,
# before `return record.model_dump()`:
    if router:
        await router._emit_event("task:created", project_id, record.model_dump())
    return record.model_dump()
```

```python
# update_agent_task — after `updated = await registry.get_agent_task(task_id)` guard,
# before `return updated.model_dump()`:
    if router:
        await router._emit_event("task:updated", project_id, updated.model_dump())
    return updated.model_dump()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_api.py::test_task_create_and_update_emit_ws_events -v`
Expected: PASS

Run: `pytest tests/ -v`
Expected: all existing tests still pass

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat(daemon): emit task:created/task:updated WebSocket events"
```

---

### Task A2: Dependency re-promotion on completion

**Files:**
- Modify: `daemon/registry.py` (add method near `_all_agent_task_deps_done`, ~line 388)
- Modify: `daemon/api.py` (`update_agent_task` handler)
- Test: `tests/test_api.py`

**Interfaces:**
- Produces: `registry.promote_ready_dependents(task_id: str) -> list[str]` — promotes every `todo` task whose deps are all `done` to `ready`; returns the promoted task ids.
- The `PATCH` handler calls it when the new status is `done` and emits `task:updated` for each promoted task.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
def test_dependency_repromotion_on_parent_done(client):
    """A todo child auto-promotes to ready when its parent is marked done."""
    res = client.post(
        "/api/projects/noor/tasks",
        json={"project": "noor", "title": "Parent", "instruction": "x"},
    )
    parent_id = res.json()["id"]

    res = client.post(
        "/api/projects/noor/tasks",
        json={"project": "noor", "title": "Child", "instruction": "y",
              "dependencies": [parent_id]},
    )
    child_id = res.json()["id"]
    assert res.json()["status"] == "todo"  # parent not done yet

    # Mark parent done — child must re-promote to ready.
    client.patch(f"/api/projects/noor/tasks/{parent_id}", json={"status": "done"})

    res = client.get("/api/projects/noor/tasks")
    child = next(t for t in res.json() if t["id"] == child_id)
    assert child["status"] == "ready"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_api.py::test_dependency_repromotion_on_parent_done -v`
Expected: FAIL — child stays `todo`

- [ ] **Step 3: Add the registry method**

```python
# In daemon/registry.py, AgentRegistry — add after _all_agent_task_deps_done:
    async def promote_ready_dependents(self, task_id: str) -> list[str]:
        """Promote todo tasks whose deps are all done to ready. Returns ids."""
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
```

- [ ] **Step 4: Call it from the PATCH handler**

```python
# In daemon/api.py update_agent_task, after the existing emit of task:updated:
    if payload.status == AgentTaskStatus.DONE:
        for pid in await registry.promote_ready_dependents(task_id):
            promoted = await registry.get_agent_task(pid)
            if promoted and router:
                await router._emit_event("task:updated", project_id, promoted.model_dump())
```

(Ensure `AgentTaskStatus` is imported in `api.py` — it is used by the payload models; if not already imported, add it to the `from daemon.models import ...` line.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_api.py::test_dependency_repromotion_on_parent_done -v`
Expected: PASS

Run: `pytest tests/ -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add daemon/registry.py daemon/api.py tests/test_api.py
git commit -m "feat(daemon): auto-promote dependents to ready when a parent completes"
```

---

### Task A3: Persist `workspace_path` + live progress endpoint

**Files:**
- Modify: `daemon/models.py` (`AgentTaskUpdatePayload`)
- Modify: `daemon/registry.py` (`update_agent_task`)
- Modify: `daemon/api.py` (pass `workspace_path`; add progress endpoint)
- Test: `tests/test_api.py`

**Interfaces:**
- `AgentTaskUpdatePayload` gains `workspace_path: Optional[str] = None`.
- `registry.update_agent_task(..., workspace_path: str | None = None)` persists it.
- Produces endpoint `POST /api/projects/{id}/tasks/{task_id}/progress` body `{"message": str}` → emits transient `task:progress` `{ id, message }`; returns `{"ok": true}`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
def test_task_progress_endpoint_emits_event(client):
    from daemon.router import Router
    import daemon.api as api_module
    api_module.router = Router(api_module.registry, api_module.graph_engine)

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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_api.py::test_task_progress_endpoint_emits_event tests/test_api.py::test_update_persists_workspace_path -v`
Expected: FAIL (404 on progress; workspace_path not persisted)

- [ ] **Step 3: Extend the model**

```python
# daemon/models.py — AgentTaskUpdatePayload
class AgentTaskUpdatePayload(BaseModel):
    status: Optional[AgentTaskStatus] = None
    assignee: Optional[str] = None
    result: Optional[str] = None
    workspace_path: Optional[str] = None
```

- [ ] **Step 4: Persist it in the registry**

```python
# daemon/registry.py — update_agent_task signature + body
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
            sets.append("status = ?"); params.append(status.value)
        if assignee is not None:
            sets.append("assignee = ?"); params.append(assignee)
        if result is not None:
            sets.append("result = ?"); params.append(result)
        if workspace_path is not None:
            sets.append("workspace_path = ?"); params.append(workspace_path)
        params.append(task_id)
        await self.db.execute(
            f"UPDATE agent_tasks SET {', '.join(sets)} WHERE id = ?", params,
        )
        await self.db.commit()
```

- [ ] **Step 5: Pass it through + add the progress endpoint**

```python
# daemon/api.py — in update_agent_task, add workspace_path to the registry call:
    await registry.update_agent_task(
        task_id,
        status=payload.status,
        assignee=payload.assignee,
        result=payload.result,
        workspace_path=payload.workspace_path,
    )
```

```python
# daemon/api.py — new endpoint (place after update_agent_task)
@app.post("/api/projects/{project_id}/tasks/{task_id}/progress")
async def task_progress(project_id: str, task_id: str, payload: dict):
    """Relay a live progress line from the worker to WebSocket clients."""
    message = str(payload.get("message", ""))
    if router:
        await router._emit_event("task:progress", project_id, {"id": task_id, "message": message})
    return {"ok": True}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: all pass

Run: `pytest tests/ -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add daemon/models.py daemon/registry.py daemon/api.py tests/test_api.py
git commit -m "feat(daemon): persist workspace_path and add task progress relay endpoint"
```

---

### Task A4: Worktree diff + merge endpoints

**Files:**
- Modify: `daemon/api.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `daemon.worktree.branch_diff`, `merge_branch`, `remove_worktree`; `registry.get_agent_task`.
- Produces:
  - `GET /api/projects/{id}/tasks/{task_id}/diff` → `{ "diff": str, "branch": str }` (empty diff if no workspace).
  - `POST /api/projects/{id}/tasks/{task_id}/merge` → `{ "merged": bool, "output": str }`.
- Branch name convention: `loom/task-<task_id>`. Base branch read from the task `result` JSON key `base_branch` (written by the worker; defaults to `"main"` if absent).

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_api.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_api.py::test_task_diff_empty_without_workspace tests/test_api.py::test_task_diff_404_for_unknown_task -v`
Expected: FAIL — endpoint not defined (404 for both)

- [ ] **Step 3: Implement the endpoints**

```python
# daemon/api.py — add after the progress endpoint
import json as _json
from daemon import worktree as _worktree

def _task_base_branch(record) -> str:
    try:
        return _json.loads(record.result or "{}").get("base_branch", "main")
    except (ValueError, TypeError):
        return "main"

@app.get("/api/projects/{project_id}/tasks/{task_id}/diff")
async def task_diff(project_id: str, task_id: str):
    record = await registry.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    branch = f"loom/task-{task_id}"
    if not record.workspace_path:
        return {"diff": "", "branch": branch}
    project = await registry.get_project(project_id)
    repo = os.path.expanduser(project.project_path) if project else record.workspace_path
    try:
        diff = await asyncio.to_thread(
            _worktree.branch_diff, repo, _task_base_branch(record), branch
        )
    except RuntimeError as exc:
        diff = f"(diff unavailable: {exc})"
    return {"diff": diff, "branch": branch}

@app.post("/api/projects/{project_id}/tasks/{task_id}/merge")
async def task_merge(project_id: str, task_id: str):
    record = await registry.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    project = await registry.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    branch = f"loom/task-{task_id}"
    ok, output = await asyncio.to_thread(
        _worktree.merge_branch, os.path.expanduser(project.project_path), branch
    )
    return {"merged": ok, "output": output}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: all pass

Run: `pytest tests/ -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat(daemon): worktree diff and merge endpoints for finished tasks"
```

---

## Phase B — The `loom worker`

A standalone, synchronous process (stdlib only). All external I/O — Claude, git, HTTP — is isolated behind overridable methods / module functions so `process_task` is unit-testable. `agent_id` convention: `f"{agent}-{project}"` (matches the daemon's `_handle_register`).

### Task B1: Worker skeleton + task eligibility filter

**Files:**
- Create: `daemon/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces:
  - `ClaudeResult` dataclass: `text: str`, `session_id: str | None`, `is_error: bool`.
  - `Worker(project, agent, project_path, base_url="http://127.0.0.1:8472", model=None, max_turns=30, poll_interval=2.5)`.
  - `Worker.agent_id -> str` (== `f"{agent}-{project}"`).
  - `Worker.eligible(tasks: list[dict]) -> list[dict]` (assigned to me, not in-flight).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_worker.py
from daemon.worker import Worker, ClaudeResult


def _worker(**kw):
    return Worker(
        project="noor", agent="claude-code",
        project_path="/tmp/noor", base_url="http://x", **kw,
    )


def test_agent_id_matches_daemon_convention():
    assert _worker().agent_id == "claude-code-noor"


def test_eligible_filters_by_assignee_and_inflight():
    w = _worker()
    tasks = [
        {"id": "1", "assignee": "claude-code-noor"},
        {"id": "2", "assignee": "someone-else"},
        {"id": "3", "assignee": "claude-code-noor"},
    ]
    w._inflight.add("3")
    eligible = w.eligible(tasks)
    assert [t["id"] for t in eligible] == ["1"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daemon.worker'`

- [ ] **Step 3: Write the skeleton**

```python
# daemon/worker.py
"""loom worker — autonomously runs Claude Code on Running tasks.

A first-party Loom process (not a third-party agent): it talks to the
daemon over HTTP, runs `claude -p` headless in an isolated git worktree,
and writes results + findings back. Single task at a time (V1).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from daemon.worktree import create_worktree, commit_all, current_branch

logger = logging.getLogger("loom.worker")


@dataclass
class ClaudeResult:
    text: str
    session_id: str | None
    is_error: bool


class Worker:
    def __init__(
        self,
        project: str,
        agent: str,
        project_path: str,
        base_url: str = "http://127.0.0.1:8472",
        model: str | None = None,
        max_turns: int = 30,
        poll_interval: float = 2.5,
    ):
        self.project = project
        self.agent = agent
        self.project_path = project_path
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.max_turns = max_turns
        self.poll_interval = poll_interval
        self.workspaces_dir = os.path.expanduser("~/.loom/workspaces")
        self._inflight: set[str] = set()
        self._stop = False

    @property
    def agent_id(self) -> str:
        return f"{self.agent}-{self.project}"

    def eligible(self, tasks: list[dict]) -> list[dict]:
        return [
            t for t in tasks
            if t.get("assignee") == self.agent_id and t["id"] not in self._inflight
        ]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add daemon/worker.py tests/test_worker.py
git commit -m "feat(worker): Worker skeleton with agent identity and task eligibility"
```

---

### Task B2: Claude invocation + HTTP/finding helpers

**Files:**
- Modify: `daemon/worker.py`

**Interfaces:**
- Produces (module fn): `run_claude(prompt, cwd, model=None, max_turns=30, resume=None, on_progress=None) -> ClaudeResult`.
- Produces (methods): `_api(method, path, body=None)`, `_get_running_tasks()`, `_patch_task(task_id, body)`, `_post_progress(task_id, message)`, `_write_finding(task_id, title, text)`, `ensure_registered()`.

> **VERIFY FIRST (Claude Code docs):** Before writing `run_claude`, confirm the headless flags and `stream-json` event schema against the official Claude Code documentation (use the `claude-code-guide` agent or the `claude-code` skill). In particular confirm: `-p`/`--print`, `--output-format stream-json` (and that it requires `--verbose`), `--permission-mode acceptEdits`, `--max-turns`, `--model`, `--resume <session_id>`, and that the terminal event is a JSON object with `type == "result"`, `result` (text), `session_id`, and `is_error`. Adjust the parsing below to match the installed version. Smoke check: `claude -p "say hi" --output-format json`.

- [ ] **Step 1: Add the implementation (no new test yet — exercised in B3)**

```python
# daemon/worker.py — add module function
def _summarize_event(event: dict) -> str:
    """One-line progress string from an assistant/tool stream event."""
    msg = event.get("message", {})
    for block in msg.get("content", []) if isinstance(msg, dict) else []:
        if block.get("type") == "tool_use":
            return f"tool: {block.get('name', '?')}"
        if block.get("type") == "text":
            return block.get("text", "")[:120]
    return "working…"


def run_claude(prompt, cwd, model=None, max_turns=30, resume=None, on_progress=None) -> ClaudeResult:
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "acceptEdits",
        "--max-turns", str(max_turns),
    ]
    if model:
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]

    proc = subprocess.Popen(
        cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    final = {"text": "", "session_id": None, "is_error": False}
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "result":
            final["text"] = event.get("result", "") or ""
            final["session_id"] = event.get("session_id")
            final["is_error"] = bool(event.get("is_error"))
        elif event.get("type") == "assistant" and on_progress:
            on_progress(_summarize_event(event))
    code = proc.wait()
    if code != 0 and not final["text"]:
        final["is_error"] = True
        final["text"] = (proc.stderr.read() or "claude exited non-zero").strip()
    return ClaudeResult(final["text"], final["session_id"], final["is_error"])
```

```python
# daemon/worker.py — add methods to Worker
    def _api(self, method: str, path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base_url}{path}", data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode() or "{}")

    def _get_running_tasks(self) -> list[dict]:
        return self._api("GET", f"/api/projects/{self.project}/tasks?status=running")

    def _patch_task(self, task_id: str, body: dict) -> dict:
        return self._api("PATCH", f"/api/projects/{self.project}/tasks/{task_id}", body)

    def _post_progress(self, task_id: str, message: str) -> None:
        try:
            self._api("POST", f"/api/projects/{self.project}/tasks/{task_id}/progress",
                      {"message": message})
        except Exception:
            pass  # progress is best-effort

    def _write_finding(self, task_id: str, title: str, text: str) -> None:
        inbox = os.path.expanduser(f"~/.loom/inbox/{self.project}")
        os.makedirs(inbox, exist_ok=True)
        fid = uuid.uuid4().hex[:8]
        ts = datetime.now(timezone.utc).isoformat()
        with open(os.path.join(inbox, f"finding-{fid}.md"), "w") as f:
            f.write(
                f"---\nagent: {self.agent}\nproject: {self.project}\n"
                f"type: general\ntimestamp: {ts}\n---\n"
                f"# Task complete: {title}\n\n{text}\n"
            )

    def ensure_registered(self) -> None:
        try:
            agents = self._api("GET", f"/api/projects/{self.project}/agents")
        except Exception:
            agents = []
        if self.agent_id not in {a.get("agent_id") for a in agents}:
            self._api("POST", f"/api/projects/{self.project}/register-agent", {
                "agent": self.agent, "version": "1.0",
                "project_path": self.project_path,
                "capabilities": ["task-execution"],
            })
```

- [ ] **Step 2: Sanity import check**

Run: `python -c "from daemon.worker import Worker, run_claude, ClaudeResult; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add daemon/worker.py
git commit -m "feat(worker): claude headless runner, HTTP client, and finding writer"
```

---

### Task B3: `process_task` — the execution lifecycle (TDD)

**Files:**
- Modify: `daemon/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `Worker.process_task(task: dict) -> None`. On success → worktree created, changes committed, finding written, task PATCHed to `done` with a JSON `result` (`summary`/`session_id`/`branch`/`base_branch`). On Claude error → PATCHed to `blocked`. Resumes a prior `session_id` if present in the task's existing `result`.

- [ ] **Step 1: Write the failing tests**

```python
# Add to tests/test_worker.py
import daemon.worker as worker_mod
from daemon.worker import Worker, ClaudeResult


class _CaptureWorker(Worker):
    """Captures PATCH/finding/progress instead of doing real I/O."""
    def __init__(self, **kw):
        super().__init__(**kw)
        self.patches = []
        self.findings = []
        self.progress = []
    def _patch_task(self, task_id, body):
        self.patches.append((task_id, body)); return {}
    def _post_progress(self, task_id, message):
        self.progress.append((task_id, message))
    def _write_finding(self, task_id, title, text):
        self.findings.append((task_id, title, text))


def _patch_git_and_claude(monkeypatch, claude_result):
    monkeypatch.setattr(worker_mod, "current_branch", lambda repo: "main")
    monkeypatch.setattr(worker_mod, "create_worktree", lambda *a, **k: None)
    monkeypatch.setattr(worker_mod, "commit_all", lambda *a, **k: True)
    monkeypatch.setattr(worker_mod, "run_claude", lambda *a, **k: claude_result)


def test_process_task_success_marks_done_and_writes_finding(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor")
    _patch_git_and_claude(monkeypatch, ClaudeResult("did the work", "sess-1", False))

    w.process_task({"id": "t1", "title": "Fix bug", "instruction": "fix it",
                    "acceptance_criteria": "", "result": None})

    final = w.patches[-1]
    assert final[0] == "t1"
    assert final[1]["status"] == "done"
    body = __import__("json").loads(final[1]["result"])
    assert body["session_id"] == "sess-1"
    assert body["branch"] == "loom/task-t1"
    assert body["base_branch"] == "main"
    assert w.findings and w.findings[0][2] == "did the work"


def test_process_task_claude_error_marks_blocked(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor")
    _patch_git_and_claude(monkeypatch, ClaudeResult("boom", "sess-2", True))

    w.process_task({"id": "t2", "title": "T", "instruction": "x",
                    "acceptance_criteria": "", "result": None})

    assert w.patches[-1][1]["status"] == "blocked"
    assert w.findings == []  # no finding on failure


def test_process_task_worktree_failure_marks_blocked(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor")
    monkeypatch.setattr(worker_mod, "current_branch", lambda repo: "main")
    def _boom(*a, **k):
        raise RuntimeError("not a git repo")
    monkeypatch.setattr(worker_mod, "create_worktree", _boom)

    w.process_task({"id": "t3", "title": "T", "instruction": "x", "result": None})
    assert w.patches[-1][1]["status"] == "blocked"
    assert "not a git repo" in w.patches[-1][1]["result"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL — `Worker` has no attribute `process_task`

- [ ] **Step 3: Implement `process_task`**

```python
# daemon/worker.py — add to Worker
    def process_task(self, task: dict) -> None:
        task_id = task["id"]
        title = task.get("title", "")
        instruction = task.get("instruction", "")
        criteria = task.get("acceptance_criteria") or ""
        branch = f"loom/task-{task_id}"
        workspace = os.path.join(self.workspaces_dir, self.project, f"task-{task_id}")

        # current_branch() + create_worktree() both require a git repo; a
        # misconfigured project_path must block the task, not crash the loop.
        try:
            base_branch = current_branch(self.project_path)
            create_worktree(self.project_path, workspace, branch, base_ref=base_branch)
        except RuntimeError as exc:
            self._patch_task(task_id, {
                "status": "blocked",
                "result": json.dumps({"branch": branch, "base_branch": "unknown",
                                      "error": f"worktree failed: {exc}"}),
            })
            return

        meta = {"branch": branch, "base_branch": base_branch}

        self._patch_task(task_id, {"workspace_path": workspace})

        prompt = instruction
        if criteria:
            prompt = f"{instruction}\n\nAcceptance criteria:\n{criteria}"

        resume = None
        try:
            prior = json.loads(task.get("result") or "{}")
            resume = prior.get("session_id")
        except (ValueError, TypeError):
            resume = None

        result = run_claude(
            prompt, cwd=workspace, model=self.model, max_turns=self.max_turns,
            resume=resume, on_progress=lambda line: self._post_progress(task_id, line),
        )

        meta["summary"] = result.text
        meta["session_id"] = result.session_id

        if result.is_error:
            meta["error"] = result.text or "claude reported an error"
            self._patch_task(task_id, {
                "status": "blocked", "result": json.dumps(meta),
                "workspace_path": workspace,
            })
            return

        commit_all(workspace, f"loom task {task_id}: {title}")
        self._write_finding(task_id, title, result.text)
        self._patch_task(task_id, {
            "status": "done", "result": json.dumps(meta),
            "workspace_path": workspace,
        })
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add daemon/worker.py tests/test_worker.py
git commit -m "feat(worker): process_task lifecycle — worktree, claude, status, findings"
```

---

### Task B4: Poll loop + `loom worker` CLI subcommand

**Files:**
- Modify: `daemon/worker.py` (add `poll_once`, `run`)
- Modify: `daemon/main.py` (add `worker` subcommand)
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `Worker.poll_once()` (process the first eligible running task, one at a time) and `Worker.run()` (register, then loop). CLI: `loom worker --project <id> --agent <name> --project-path <path> [--base-url ...] [--model ...] [--max-turns N] [--poll 2.5]`.

- [ ] **Step 1: Write the failing test**

```python
# Add to tests/test_worker.py
def test_poll_once_processes_one_eligible_task(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor")
    monkeypatch.setattr(
        w, "_get_running_tasks",
        lambda: [
            {"id": "a", "assignee": "claude-code-noor", "title": "A", "instruction": "x", "result": None},
            {"id": "b", "assignee": "other", "title": "B", "instruction": "y", "result": None},
        ],
    )
    processed = []
    monkeypatch.setattr(w, "process_task", lambda task: processed.append(task["id"]))

    w.poll_once()
    assert processed == ["a"]  # only the assigned one, one at a time
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_worker.py::test_poll_once_processes_one_eligible_task -v`
Expected: FAIL — `Worker` has no attribute `poll_once`

- [ ] **Step 3: Implement the loop**

```python
# daemon/worker.py — add to Worker
    def poll_once(self) -> None:
        for task in self.eligible(self._get_running_tasks()):
            self._inflight.add(task["id"])
            try:
                self.process_task(task)
            finally:
                self._inflight.discard(task["id"])
            return  # one task per tick (V1)

    def run(self) -> None:
        self.ensure_registered()
        logger.info("worker %s online for project %s", self.agent_id, self.project)
        while not self._stop:
            try:
                self.poll_once()
            except Exception as exc:  # never let the loop die
                logger.warning("poll error: %s", exc)
            time.sleep(self.poll_interval)
```

- [ ] **Step 4: Add the CLI subcommand**

```python
# daemon/main.py — add the command handler
def cmd_worker(args):
    """Run a Loom worker that executes Running tasks with Claude Code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    from daemon.worker import Worker
    Worker(
        project=args.project,
        agent=args.agent,
        project_path=os.path.expanduser(args.project_path),
        base_url=args.base_url,
        model=args.model,
        max_turns=args.max_turns,
        poll_interval=args.poll,
    ).run()
```

```python
# daemon/main.py — register in KNOWN_SUBCOMMANDS and add the subparser
# 1) Update the set:
    KNOWN_SUBCOMMANDS = {"start", "register", "unregister", "detect-agents", "worker"}

# 2) After the detect-agents subparser block:
    # ---- loom worker ----
    worker_p = sub.add_parser("worker", help="Run a worker that executes Running tasks with Claude Code")
    worker_p.add_argument("--project", required=True, help="Project identifier")
    worker_p.add_argument("--agent", default="claude-code", help="Agent name (default: claude-code)")
    worker_p.add_argument("--project-path", required=True, help="Absolute path to the git project")
    worker_p.add_argument("--base-url", default="http://127.0.0.1:8472", help="Daemon base URL")
    worker_p.add_argument("--model", default=None, help="Claude model (optional)")
    worker_p.add_argument("--max-turns", type=int, default=30, help="Max Claude turns per task")
    worker_p.add_argument("--poll", type=float, default=2.5, help="Poll interval seconds")
    worker_p.set_defaults(func=cmd_worker)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (all)

Run: `loom worker --help`
Expected: usage text listing `--project`, `--agent`, `--project-path`, etc.

- [ ] **Step 6: Commit**

```bash
git add daemon/worker.py daemon/main.py tests/test_worker.py
git commit -m "feat(worker): poll loop and `loom worker` CLI subcommand"
```

---

### Task B5: Worker heartbeat (keep the worker shown online)

**Files:**
- Modify: `daemon/worker.py`

**Interfaces:**
- Produces: `Worker._heartbeat()` writes `heartbeat.json` to the inbox (reusing the existing heartbeat mechanism — the daemon watcher marks the agent online, no graph rebuild). Called from `run()`, throttled to ~30s.

- [ ] **Step 1: Add the heartbeat method + throttle**

```python
# daemon/worker.py — add to Worker
    def _heartbeat(self) -> None:
        inbox = os.path.expanduser(f"~/.loom/inbox/{self.project}")
        os.makedirs(inbox, exist_ok=True)
        with open(os.path.join(inbox, "heartbeat.json"), "w") as f:
            json.dump({
                "agent": self.agent,
                "project": self.project,
                "status": "online",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }, f)
```

- [ ] **Step 2: Call it from `run()` (throttled)**

```python
# daemon/worker.py — replace the run() body with the throttled version
    def run(self) -> None:
        self.ensure_registered()
        logger.info("worker %s online for project %s", self.agent_id, self.project)
        last_hb = 0.0
        while not self._stop:
            now = time.monotonic()
            if now - last_hb > 30:
                try:
                    self._heartbeat()
                except Exception as exc:
                    logger.warning("heartbeat failed: %s", exc)
                last_hb = now
            try:
                self.poll_once()
            except Exception as exc:  # never let the loop die
                logger.warning("poll error: %s", exc)
            time.sleep(self.poll_interval)
```

- [ ] **Step 3: Sanity check + commit**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (existing worker tests unaffected)

```bash
git add daemon/worker.py
git commit -m "feat(worker): periodic heartbeat so the worker shows online"
```

---

## Phase C — Dashboard

> **Before writing any code in this phase**, read `dashboard/node_modules/next/dist/docs/` for the relevant Next 16 guidance (per `dashboard/AGENTS.md`). All pages here are **client components** mirroring `graph/page.tsx`; modals mirror the native-`<dialog>` pattern in `dispatch-modal.tsx`. There is **no test runner** for the dashboard — each task verifies with `npm run lint` (run from `dashboard/`) and a manual check.

### Task C1: API client wrappers + types

**Files:**
- Modify: `dashboard/lib/api.ts` (append; reuses existing `BASE_URL` + `fetchApi`)

**Interfaces:**
- Produces: `AgentTask`, `AgentTaskStatus`, `CreateAgentTaskPayload`, `UpdateAgentTaskPayload`, and `listAgentTasks`/`createAgentTask`/`updateAgentTask`/`getTaskDiff`/`mergeTask`.

- [ ] **Step 1: Append to `dashboard/lib/api.ts`**

```typescript
// --- Agent Task Board (Kanban) ---
export type AgentTaskStatus =
  | "triage" | "todo" | "ready" | "running" | "blocked" | "done" | "archived";

export interface AgentTask {
  id: string;
  project: string;
  title: string;
  instruction: string;
  status: AgentTaskStatus;
  assignee: string | null;
  priority: number;
  dependencies: string[];
  acceptance_criteria: string;
  created_at: string;
  updated_at: string;
  workspace_path: string | null;
}

export interface CreateAgentTaskPayload {
  title: string;
  instruction: string;
  assignee?: string | null;
  priority?: number;
  dependencies?: string[];
  acceptance_criteria?: string;
}

export interface UpdateAgentTaskPayload {
  status?: AgentTaskStatus;
  assignee?: string | null;
  result?: string;
  workspace_path?: string;
}

export async function listAgentTasks(projectId: string, status?: AgentTaskStatus): Promise<AgentTask[]> {
  const q = status ? `?status=${status}` : "";
  return fetchApi(`/api/projects/${projectId}/tasks${q}`);
}

export async function createAgentTask(projectId: string, payload: CreateAgentTaskPayload): Promise<AgentTask> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ project: projectId, ...payload }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function updateAgentTask(projectId: string, taskId: string, payload: UpdateAgentTaskPayload): Promise<AgentTask> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function getTaskDiff(projectId: string, taskId: string): Promise<{ diff: string; branch: string }> {
  return fetchApi(`/api/projects/${projectId}/tasks/${taskId}/diff`);
}

export async function mergeTask(projectId: string, taskId: string): Promise<{ merged: boolean; output: string }> {
  const res = await fetch(`${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/merge`, { method: "POST" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Verify + commit**

Run (from `dashboard/`): `npm run lint`
Expected: no new errors.

```bash
git add dashboard/lib/api.ts
git commit -m "feat(dashboard): agent-task API client wrappers and types"
```

---

### Task C2: Tasks route page

**Files:**
- Create: `dashboard/app/[locale]/projects/[id]/tasks/page.tsx`

**Interfaces:**
- Consumes: `listAgentTasks`, `getProject`, `updateAgentTask`, `useWebSocket`, and `<TaskBoard>`/`<NewTaskModal>`/`<TaskDetailDrawer>` (built in C3–C5). Renders nothing testable until those exist — build C3–C5 in the same session before linting C2's imports.

- [ ] **Step 1: Create the page**

```tsx
"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  listAgentTasks, getProject, updateAgentTask,
  type AgentTask, type AgentTaskStatus, type AgentInfo,
} from "@/lib/api";
import { useWebSocket } from "@/lib/use-websocket";
import { TaskBoard } from "@/components/task-board";
import { NewTaskModal } from "@/components/new-task-modal";
import { TaskDetailDrawer } from "@/components/task-detail-drawer";

export default function TasksPage() {
  const t = useTranslations("TaskBoard");
  const { id } = useParams<{ id: string }>();
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [selected, setSelected] = useState<AgentTask | null>(null);
  const { subscribe } = useWebSocket();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [taskList, project] = await Promise.all([listAgentTasks(id), getProject(id)]);
      setTasks(taskList);
      setAgents(project.agents || []);
    } catch {
      // no tasks yet
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const upsert = (task: AgentTask) =>
      setTasks((prev) => {
        const i = prev.findIndex((x) => x.id === task.id);
        if (i === -1) return [task, ...prev];
        const next = [...prev]; next[i] = task; return next;
      });
    return subscribe(`project:${id}`, (event) => {
      if (event.event === "task:created" || event.event === "task:updated") {
        upsert(event.data as unknown as AgentTask);
      }
    });
  }, [id, subscribe]);

  async function handleMove(taskId: string, status: AgentTaskStatus) {
    setTasks((prev) => prev.map((x) => (x.id === taskId ? { ...x, status } : x)));
    try {
      const updated = await updateAgentTask(id, taskId, { status });
      setTasks((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
    } catch {
      load();
    }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-96 text-zinc-500">{t("loading")}</div>;
  }

  return (
    <div className="flex flex-col h-[calc(100vh-6rem)]">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h2 className="text-xl font-bold">{t("heading")}</h2>
          <p className="text-xs text-zinc-500">{t("count", { count: tasks.length })}</p>
        </div>
        <Button size="sm" onClick={() => setModalOpen(true)}>
          <Plus className="w-3.5 h-3.5 me-1" />
          {t("newTask")}
        </Button>
      </div>

      <TaskBoard tasks={tasks} onMove={handleMove} onSelect={setSelected} />

      <NewTaskModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        projectId={id}
        agents={agents}
        tasks={tasks}
        onCreated={load}
      />

      <TaskDetailDrawer
        task={selected}
        projectId={id}
        agents={agents}
        onClose={() => setSelected(null)}
        onChanged={load}
      />
    </div>
  );
}
```

- [ ] **Step 2: Commit (after C3–C5 exist and lint passes)**

```bash
git add dashboard/app/[locale]/projects/[id]/tasks/page.tsx
git commit -m "feat(dashboard): tasks route with live board, modal, and detail drawer"
```

---

### Task C3: TaskBoard component (columns + native drag-and-drop)

**Files:**
- Create: `dashboard/components/task-board.tsx`

**Interfaces:**
- Produces: `<TaskBoard tasks onMove onSelect />` where `onMove(taskId, status)` and `onSelect(task)`. Five columns; cards are `draggable`; dropping on a column calls `onMove`. (Native HTML5 DnD — no dependency. Spec named `@dnd-kit`; this is a deliberate refinement to add zero deps and avoid React-19 peer-dep risk.)

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { GripVertical } from "lucide-react";
import type { AgentTask, AgentTaskStatus } from "@/lib/api";

const COLUMNS: { status: AgentTaskStatus; key: string; color: string }[] = [
  { status: "todo", key: "todo", color: "text-zinc-400" },
  { status: "ready", key: "ready", color: "text-blue-400" },
  { status: "running", key: "running", color: "text-amber-400" },
  { status: "blocked", key: "blocked", color: "text-red-400" },
  { status: "done", key: "done", color: "text-emerald-400" },
];

interface TaskBoardProps {
  tasks: AgentTask[];
  onMove: (taskId: string, status: AgentTaskStatus) => void;
  onSelect: (task: AgentTask) => void;
}

export function TaskBoard({ tasks, onMove, onSelect }: TaskBoardProps) {
  const t = useTranslations("TaskBoard");
  const [dragId, setDragId] = useState<string | null>(null);
  const [overCol, setOverCol] = useState<AgentTaskStatus | null>(null);

  return (
    <div className="grid grid-cols-5 gap-3 flex-1 min-h-0">
      {COLUMNS.map((col) => {
        const colTasks = tasks.filter((x) => x.status === col.status);
        return (
          <div
            key={col.status}
            onDragOver={(e) => { e.preventDefault(); setOverCol(col.status); }}
            onDragLeave={() => setOverCol((c) => (c === col.status ? null : c))}
            onDrop={() => {
              if (dragId) onMove(dragId, col.status);
              setDragId(null); setOverCol(null);
            }}
            className={`flex flex-col rounded-lg border p-2 overflow-y-auto transition-colors ${
              overCol === col.status ? "border-zinc-600 bg-zinc-900/60" : "border-zinc-800 bg-zinc-950"
            }`}
          >
            <div className="flex items-center gap-2 mb-2 px-1">
              <span className={`text-xs font-semibold ${col.color}`}>{t(`columns.${col.key}`)}</span>
              <span className="text-xs text-zinc-600">{colTasks.length}</span>
            </div>
            <div className="space-y-2">
              {colTasks.map((task) => (
                <div
                  key={task.id}
                  draggable
                  onDragStart={() => setDragId(task.id)}
                  onDragEnd={() => { setDragId(null); setOverCol(null); }}
                  onClick={() => onSelect(task)}
                  className="group cursor-pointer rounded-md border border-zinc-800 bg-zinc-900 p-2 hover:border-zinc-700"
                >
                  <div className="flex items-start gap-1">
                    <GripVertical className="w-3 h-3 mt-0.5 text-zinc-700 group-hover:text-zinc-500 shrink-0" />
                    <p className="text-xs font-medium text-zinc-200 line-clamp-2">{task.title}</p>
                  </div>
                  <div className="flex items-center gap-2 mt-1 ps-4">
                    {task.assignee && <span className="text-[10px] text-zinc-500 truncate">{task.assignee}</span>}
                    {task.priority > 0 && <span className="text-[10px] text-amber-500">P{task.priority}</span>}
                    {task.dependencies.length > 0 && (
                      <span className="text-[10px] text-zinc-600">⛓ {task.dependencies.length}</span>
                    )}
                  </div>
                </div>
              ))}
              {colTasks.length === 0 && (
                <p className="text-[10px] text-zinc-700 px-1 py-2">{t("emptyColumn")}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/components/task-board.tsx
git commit -m "feat(dashboard): Kanban TaskBoard with native drag-and-drop"
```

---

### Task C4: NewTaskModal component

**Files:**
- Create: `dashboard/components/new-task-modal.tsx`

**Interfaces:**
- Produces: `<NewTaskModal open onClose projectId agents tasks onCreated />`. "Auto" assignee resolves to the first `online` agent's `agent_id` (or `null`). Priority low/medium/high maps to int 0/1/2.

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { createAgentTask, type AgentInfo, type AgentTask } from "@/lib/api";

const PRIORITY_MAP: Record<string, number> = { low: 0, medium: 1, high: 2 };

interface NewTaskModalProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  agents: AgentInfo[];
  tasks: AgentTask[];
  onCreated: () => void;
}

export function NewTaskModal({ open, onClose, projectId, agents, tasks, onCreated }: NewTaskModalProps) {
  const t = useTranslations("NewTaskModal");
  const tPriority = useTranslations("Common.priority");
  const ref = useRef<HTMLDialogElement>(null);
  const [title, setTitle] = useState("");
  const [instruction, setInstruction] = useState("");
  const [assignee, setAssignee] = useState(""); // "" = Auto
  const [priority, setPriority] = useState("medium");
  const [deps, setDeps] = useState<string[]>([]);
  const [criteria, setCriteria] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    else if (!open && d.open) d.close();
  }, [open]);

  function resolveAssignee(): string | null {
    if (assignee) return assignee;
    const online = agents.find((a) => a.status === "online");
    return online ? online.agent_id : null;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !instruction.trim()) return;
    setLoading(true); setError("");
    try {
      await createAgentTask(projectId, {
        title, instruction,
        assignee: resolveAssignee(),
        priority: PRIORITY_MAP[priority],
        dependencies: deps,
        acceptance_criteria: criteria,
      });
      onCreated(); onClose();
      setTitle(""); setInstruction(""); setDeps([]); setCriteria("");
    } catch {
      setError(t("error"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={() => { if (open) onClose(); }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      className="rounded-xl p-0 bg-transparent max-w-none"
    >
      <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-[520px] p-6">
        <h2 className="text-lg font-bold text-zinc-100 mb-4">{t("heading")}</h2>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("title")}</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200"
              required
            />
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("instruction")}</label>
            <textarea
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              placeholder={t("instructionPlaceholder")}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-24 resize-none"
              required
            />
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("assignee")}</label>
            <select
              value={assignee}
              onChange={(e) => setAssignee(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200"
            >
              <option value="">{t("autoAssign")}</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>{a.agent_name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("priority")}</label>
            <div className="flex gap-2">
              {(["low", "medium", "high"] as const).map((p) => (
                <button
                  key={p}
                  type="button"
                  onClick={() => setPriority(p)}
                  className={`px-3 py-1 text-xs rounded-full border transition-colors ${
                    priority === p
                      ? "border-amber-700 bg-amber-900/30 text-amber-300"
                      : "border-zinc-700 text-zinc-500 hover:text-zinc-300"
                  }`}
                >
                  {tPriority(p)}
                </button>
              ))}
            </div>
          </div>
          {tasks.length > 0 && (
            <div>
              <label className="text-xs text-zinc-400 mb-1 block">{t("dependencies")}</label>
              <select
                multiple
                value={deps}
                onChange={(e) => setDeps(Array.from(e.target.selectedOptions, (o) => o.value))}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-20"
              >
                {tasks.map((task) => (
                  <option key={task.id} value={task.id}>{task.title}</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="text-xs text-zinc-400 mb-1 block">{t("acceptanceCriteria")}</label>
            <textarea
              value={criteria}
              onChange={(e) => setCriteria(e.target.value)}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-3 py-2 text-sm text-zinc-200 h-16 resize-none"
            />
          </div>
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <div className="flex gap-2 pt-2">
            <Button type="submit" disabled={loading} className="flex-1">
              {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
              <span className="ms-2">{t("create")}</span>
            </Button>
            <Button type="button" variant="outline" onClick={onClose}>{t("cancel")}</Button>
          </div>
        </form>
      </div>
    </dialog>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add dashboard/components/new-task-modal.tsx
git commit -m "feat(dashboard): NewTaskModal for creating and assigning tasks"
```

---

### Task C5: TaskDetailDrawer component

**Files:**
- Create: `dashboard/components/task-detail-drawer.tsx`

**Interfaces:**
- Produces: `<TaskDetailDrawer task projectId agents onClose onChanged />`. Fetches the diff for `done`/`blocked` tasks; supports merge, status change, and reassignment. Parses the worker's JSON `result` for a human summary.

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { X, GitMerge, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  getTaskDiff, mergeTask, updateAgentTask,
  type AgentTask, type AgentInfo, type AgentTaskStatus,
} from "@/lib/api";

const STATUSES: AgentTaskStatus[] = ["triage", "todo", "ready", "running", "blocked", "done", "archived"];

interface TaskDetailDrawerProps {
  task: AgentTask | null;
  projectId: string;
  agents: AgentInfo[];
  onClose: () => void;
  onChanged: () => void;
}

function parseSummary(result: string | null): string {
  if (!result) return "";
  try {
    const parsed = JSON.parse(result);
    return parsed.summary || parsed.error || result;
  } catch {
    return result;
  }
}

export function TaskDetailDrawer({ task, projectId, agents, onClose, onChanged }: TaskDetailDrawerProps) {
  const t = useTranslations("TaskDetail");
  const [diff, setDiff] = useState("");
  const [merging, setMerging] = useState(false);
  const [mergeMsg, setMergeMsg] = useState("");

  useEffect(() => {
    setDiff(""); setMergeMsg("");
    if (task && (task.status === "done" || task.status === "blocked")) {
      getTaskDiff(projectId, task.id).then((d) => setDiff(d.diff)).catch(() => {});
    }
  }, [task, projectId]);

  if (!task) return null;

  async function handleMerge() {
    setMerging(true); setMergeMsg("");
    try {
      const res = await mergeTask(projectId, task!.id);
      setMergeMsg(res.merged ? t("mergeOk") : t("mergeConflict"));
      if (res.merged) onChanged();
    } catch {
      setMergeMsg(t("mergeConflict"));
    } finally {
      setMerging(false);
    }
  }

  async function handleStatus(status: AgentTaskStatus) {
    await updateAgentTask(projectId, task!.id, { status });
    onChanged();
  }

  async function handleAssignee(assignee: string) {
    await updateAgentTask(projectId, task!.id, { assignee: assignee || null });
    onChanged();
  }

  return (
    <div className="fixed inset-y-0 end-0 w-[420px] bg-zinc-950 border-s border-zinc-800 shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-zinc-800">
        <h3 className="text-sm font-bold text-zinc-100 truncate">{task.title}</h3>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300"><X className="w-4 h-4" /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        <div>
          <label className="text-zinc-500 block mb-1">{t("status")}</label>
          <select
            value={task.status}
            onChange={(e) => handleStatus(e.target.value as AgentTaskStatus)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1.5 text-zinc-200"
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label className="text-zinc-500 block mb-1">{t("assignee")}</label>
          <select
            value={task.assignee || ""}
            onChange={(e) => handleAssignee(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1.5 text-zinc-200"
          >
            <option value="">{t("unassigned")}</option>
            {agents.map((a) => <option key={a.agent_id} value={a.agent_id}>{a.agent_name}</option>)}
          </select>
        </div>
        <div>
          <label className="text-zinc-500 block mb-1">{t("instruction")}</label>
          <p className="text-zinc-300 whitespace-pre-wrap">{task.instruction}</p>
        </div>
        {task.acceptance_criteria && (
          <div>
            <label className="text-zinc-500 block mb-1">{t("acceptanceCriteria")}</label>
            <p className="text-zinc-300 whitespace-pre-wrap">{task.acceptance_criteria}</p>
          </div>
        )}
        {task.result && (
          <div>
            <label className="text-zinc-500 block mb-1">{t("result")}</label>
            <p className="text-zinc-300 whitespace-pre-wrap">{parseSummary(task.result)}</p>
          </div>
        )}
        {diff && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-zinc-500">{t("diff")}</label>
              <Button size="sm" variant="outline" onClick={handleMerge} disabled={merging}>
                {merging ? <Loader2 className="w-3 h-3 animate-spin" /> : <GitMerge className="w-3 h-3" />}
                <span className="ms-1">{t("merge")}</span>
              </Button>
            </div>
            {mergeMsg && <p className="text-[10px] text-zinc-400 mb-1">{mergeMsg}</p>}
            <pre className="bg-black/50 border border-zinc-800 rounded p-2 text-[10px] text-zinc-300 overflow-x-auto max-h-64">{diff}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Lint the whole dashboard + commit**

Run (from `dashboard/`): `npm run lint`
Expected: no new errors across C2–C5.

```bash
git add dashboard/components/task-detail-drawer.tsx
git commit -m "feat(dashboard): TaskDetailDrawer with diff, merge, and status/assignee controls"
```

---

### Task C6: i18n strings + navigation link

**Files:**
- Modify: `dashboard/messages/en.json`, `dashboard/messages/ar.json`
- Modify: the project nav (find the existing "Graph" link under `dashboard/app/[locale]/projects/[id]/`)

- [ ] **Step 1: Add the `en.json` namespaces** (top level of the messages object)

```json
"TaskBoard": {
  "heading": "Task Board",
  "loading": "Loading tasks…",
  "count": "{count} tasks",
  "newTask": "New Task",
  "emptyColumn": "No tasks",
  "columns": { "todo": "To Do", "ready": "Ready", "running": "Running", "blocked": "Blocked", "done": "Done" }
},
"NewTaskModal": {
  "heading": "New Task",
  "title": "Title",
  "instruction": "Instruction",
  "instructionPlaceholder": "What should the agent do?",
  "assignee": "Assignee",
  "autoAssign": "Auto (first online agent)",
  "priority": "Priority",
  "dependencies": "Depends on",
  "acceptanceCriteria": "Acceptance criteria",
  "create": "Create",
  "cancel": "Cancel",
  "error": "Could not create task"
},
"TaskDetail": {
  "status": "Status",
  "assignee": "Assignee",
  "unassigned": "Unassigned",
  "instruction": "Instruction",
  "acceptanceCriteria": "Acceptance criteria",
  "result": "Result",
  "diff": "Changes",
  "merge": "Merge",
  "mergeOk": "Merged into the project branch.",
  "mergeConflict": "Merge failed — resolve conflicts manually."
}
```

- [ ] **Step 2: Add the `ar.json` namespaces** (same keys, Arabic values)

```json
"TaskBoard": {
  "heading": "لوحة المهام",
  "loading": "جارٍ تحميل المهام…",
  "count": "{count} مهمة",
  "newTask": "مهمة جديدة",
  "emptyColumn": "لا توجد مهام",
  "columns": { "todo": "قيد الانتظار", "ready": "جاهزة", "running": "قيد التنفيذ", "blocked": "متوقفة", "done": "منجزة" }
},
"NewTaskModal": {
  "heading": "مهمة جديدة",
  "title": "العنوان",
  "instruction": "التعليمات",
  "instructionPlaceholder": "ما الذي يجب أن يقوم به الوكيل؟",
  "assignee": "المُسنَدة إليه",
  "autoAssign": "تلقائي (أول وكيل متصل)",
  "priority": "الأولوية",
  "dependencies": "تعتمد على",
  "acceptanceCriteria": "معايير القبول",
  "create": "إنشاء",
  "cancel": "إلغاء",
  "error": "تعذّر إنشاء المهمة"
},
"TaskDetail": {
  "status": "الحالة",
  "assignee": "المُسنَدة إليه",
  "unassigned": "غير مُسنَدة",
  "instruction": "التعليمات",
  "acceptanceCriteria": "معايير القبول",
  "result": "النتيجة",
  "diff": "التغييرات",
  "merge": "دمج",
  "mergeOk": "تم الدمج في فرع المشروع.",
  "mergeConflict": "فشل الدمج — قم بحل التعارضات يدويًا."
}
```

> `NewTaskModal`/`TaskDetail` reuse `Common.priority.{low,medium,high}`, which already exist (used by `dispatch-modal.tsx`). Verify those keys are present in both files; if missing, add them.

- [ ] **Step 3: Add the "Tasks" nav link**

Find the existing "Graph" link: `grep -rn "graph" dashboard/app/[locale]/projects/[id]/` — it lives in the project's layout or page nav. Add an analogous entry pointing to the `tasks` route, mirroring the existing one exactly. Example (using the project's i18n `Link`):

```tsx
// Beside the existing Graph link:
<Link href={`/projects/${id}/tasks`} className={/* same classes as the Graph link */}>
  {t("tasks")}
</Link>
```

Add the `"tasks"` label to the same translations namespace the nav uses, in both `en.json` (`"Tasks"`) and `ar.json` (`"المهام"`).

- [ ] **Step 4: Verify + commit**

Run (from `dashboard/`): `npm run lint` and `npm run build`
Expected: build succeeds; the `/projects/<id>/tasks` route compiles.

```bash
git add dashboard/messages/en.json dashboard/messages/ar.json dashboard/app/[locale]/projects/[id]
git commit -m "feat(dashboard): i18n strings and Tasks nav link"
```

---

## Phase D — Documentation & end-to-end verification

### Task D1: Document `loom worker` + the Tasks board

**Files:**
- Modify: `README.md` (and `CLAUDE.md` if it documents commands/architecture)

- [ ] **Step 1: Add a "Task Board & Worker" section to `README.md`**

Document: the Tasks board (create/assign/drag), the 7-state lifecycle, and how to run the worker:

```bash
# 1. Start the daemon
loom --port 8472
# 2. Start a worker for a project (separate terminal; project must be a git repo)
loom worker --project my-project --agent claude-code --project-path /abs/path/to/my-project
# 3. In the dashboard, open the project's Tasks tab, create a task, assign it to
#    the worker's agent, and drag it to "Running" — the worker runs Claude Code in
#    an isolated git worktree and moves the card to Done with a reviewable diff.
```

Note the safety model: the worker edits an isolated `git worktree` (branch `loom/task-<id>`); merges are user-initiated from the task detail drawer.

- [ ] **Step 2: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: document the Kanban task board and loom worker"
```

---

### Task D2: Full-suite + end-to-end verification

- [ ] **Step 1: Backend suite is green**

Run: `pytest tests/ -v`
Expected: all tests pass (the original suite **plus** `test_worktree.py`, `test_worker.py`, and the new `test_api.py` cases).

- [ ] **Step 2: Dashboard builds**

Run (from `dashboard/`): `npm run lint && npm run build`
Expected: lint clean; production build succeeds; `/[locale]/projects/[id]/tasks` route compiles.

- [ ] **Step 3: Manual end-to-end walkthrough**

Start the daemon (`loom --port 8472`), the dashboard (`npm run dev`), and a worker pointed at a throwaway git repo. Then verify:

- [ ] Create a task in the **New Task** modal; it appears in **Todo**.
- [ ] Assign it to the worker's agent; drag it to **Running**.
- [ ] The worker creates a worktree and the card progresses; on success it lands in **Done** (or **Blocked** on failure).
- [ ] Open the card → the **diff** renders; **Merge** brings the change into the project branch.
- [ ] A `finding-*.md` appears under `~/.loom/inbox/<project>/` and the graph updates (auto-retain).
- [ ] Dependency check: task B depends on A; completing A auto-promotes B from **Todo** to **Ready**.
- [ ] Switch the locale to `ar` → board labels are translated and right-to-left.

- [ ] **Step 4: Finalize**

```bash
git status   # confirm only intended files changed
```

Then use the `superpowers:finishing-a-development-branch` skill to choose how to integrate `feat/kanban-task-board` (merge / PR / cleanup).

---

## Self-Review

Reviewed the plan against the spec with fresh eyes.

**1. Spec coverage** — every spec section maps to a task:
- §5 A1–A4 (daemon: WS events, re-promotion, progress, diff/merge) → Tasks A1–A4.
- §6 B1–B7 (worker: identity, poll/claim, worktree, claude, transitions+resume, auto-retain, config) → Phase 0 + Tasks B1–B5.
- §7 C1–C4 (dashboard: wrappers, route, components, i18n) → Tasks C1–C6.
- §8 WS contract, §9 `workspace_path`, §10 worktree/merge, §11 safety, §12 testing → covered across A1/A3/A4, Phase 0, and Phase D.

**2. Placeholder scan** — no `TBD`/`TODO`/"add error handling"/"similar to" placeholders; every code step contains real code. The two explicit *deferrals* are deliberate and specified: (a) Claude Code flag/schema verification (Task B2, with exact items to confirm), (b) locating the existing Graph nav link (Task C6, with example code).

**3. Type consistency** — verified signatures match across tasks: `run_claude(...)` (B2) ↔ its call (B3); `ClaudeResult` fields; `create_worktree`/`commit_all`/`current_branch`/`branch_diff`/`merge_branch` (Phase 0) ↔ their callers (A4, B3); `update_agent_task(..., workspace_path=...)` (A3) ↔ worker PATCH bodies; `promote_ready_dependents` (A2); the dashboard `AgentTask` interface ↔ the `AgentTaskRecord` columns.

**Deliberate refinements vs the spec (flagged for the user):**
- **Native HTML5 drag-and-drop** instead of `@dnd-kit` — zero new dashboard dependencies; honors the "no new infra" constraint and avoids a React-19/Next-16 peer-dep risk.
- **Worker → daemon over stdlib `urllib`** instead of `httpx` — zero new Python dependencies.
- **`result` stored as JSON** (`summary`/`session_id`/`branch`/`base_branch`) so resume + diff need no schema migration; the UI parses it (falls back to plain text).

**Known minor deferral:** `task:progress` events are emitted and relayed (Task A3) but the board doesn't yet render per-step progress on the running card — status transitions (`running`→`done`) already update live via `task:updated`. Surfacing the streamed line on the card is a small follow-up, not a blocker.
