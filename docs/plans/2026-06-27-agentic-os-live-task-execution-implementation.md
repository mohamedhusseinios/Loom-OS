# Live Task-Execution View & Dashboard-Launched Workers — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a Kanban task *run* when moved to Running, show a persisted read-only "chat window" of the agent's progress, and surface whether a worker is actually attached.

**Architecture:** The daemon spawns a one-shot `loom worker --once --task <id>` subprocess per task (tracked by a new `WorkerSupervisor`), the worker posts narrative progress lines that are now persisted to a `task_progress` table and relayed over WebSocket, and the task detail drawer becomes a live transcript with worker-status + Run/Stop controls.

**Tech Stack:** Python 3.10+ / FastAPI / aiosqlite / pytest (asyncio_mode=auto); Next.js 16 / React 19 / next-intl 4 / Tailwind v4 / shadcn.

**Spec:** `docs/superpowers/specs/2026-06-27-agentic-os-live-task-execution-design.md`

## Global Constraints

- **Module-global singletons, not DI.** Route handlers read `daemon/api.py` module globals (`registry`, `router`, `graph_engine`, and the new `supervisor`). Tests inject temp-backed instances before constructing `TestClient`. The `lifespan` test-mode sentinel is `test_mode = registry is not None`; in test mode it must NOT create a real `WorkerSupervisor` (would fork real subprocesses).
- **Idempotent spawn.** Moving a task to Running must spawn at most one worker (guard on `supervisor.is_running(task_id)`), mirroring the existing dispatch dual-write idempotency contract.
- **aiosqlite row access by name** — `self.db.row_factory = aiosqlite.Row` is already set (registry.py:32); new queries use `row["col"]`.
- **i18n in BOTH locales.** Every new UI string goes in `dashboard/messages/en.json` AND `dashboard/messages/ar.json` (ar is RTL).
- **Hardcoded endpoints.** Dashboard talks to `BASE_URL = "http://localhost:8472"` (lib/api.ts:1); WS at `ws://localhost:8472/ws`. CORS allows only `http://localhost:3000`.
- **No JS test runner exists.** Frontend tasks are gated by `npm run lint` + `npm run build` (type-check) and a manual smoke step — not unit tests. Backend uses pytest TDD.
- **Conventional commits** (`feat:`, `docs:`, `chore:`).
- **Worker budget:** per-task `--max-budget-usd` (default 5.0). No global cap (out of scope).

## File Structure

**Create:**
- `daemon/supervisor.py` — `WorkerSupervisor`: spawn/track/stop one-shot worker subprocesses (one per task).
- `tests/test_supervisor.py` — supervisor unit tests with a fake `Popen`.

**Modify:**
- `daemon/models.py` — `TaskProgressPayload.kind`; new `TaskProgressRecord`.
- `daemon/registry.py` — `task_progress` table in `initialize()`; `append_progress()`, `list_progress()`.
- `daemon/api.py` — `supervisor` global + lifespan init; spawn hook in `update_agent_task`; persist in `task_progress`; new `GET /tasks/{id}/progress`, `POST /tasks/{id}/worker/start`, `POST /tasks/{id}/worker/stop`, `GET /projects/{id}/workers`; `_start_worker_for` helper.
- `daemon/worker.py` — `_post_progress(kind=...)`; milestone posts in `process_task`; `run_once(task_id)`.
- `daemon/main.py` — `--once`/`--task` flags; one-shot branch in `cmd_worker`.
- `tests/test_worker.py` — update `_CaptureWorker._post_progress` signature; one-shot + milestone tests.
- `tests/test_api.py` — fixture resets `supervisor=None`; update progress-event test to new shape; persistence + spawn-hook + worker-endpoint tests.
- `dashboard/lib/api.ts` — `TaskProgressItem` type + `getTaskProgress`/`listWorkers`/`startWorker`/`stopWorker`.
- `dashboard/app/[locale]/projects/[id]/tasks/page.tsx` — track `workerIds`, seed from `listWorkers`, maintain via WS events, pass to drawer.
- `dashboard/components/task-detail-drawer.tsx` — chat window: worker pill, Run/Stop, transcript (history + live), no-worker banner.
- `dashboard/messages/en.json` + `dashboard/messages/ar.json` — new `TaskDetail` keys.

---

## Task 1: Persist progress in the registry

**Files:**
- Modify: `daemon/models.py:208` (after `TaskProgressPayload`)
- Modify: `daemon/registry.py` — `initialize()` (~after line 88) and a new method block (after `update_agent_task`, ~line 314)
- Test: `tests/test_registry.py` (append a new test)

**Interfaces:**
- Produces: `TaskProgressRecord{task_id:str, seq:int, kind:str, message:str, ts:str}`; `AgentRegistry.append_progress(task_id:str, kind:str, message:str) -> int` (returns the new seq, 1-based); `AgentRegistry.list_progress(task_id:str) -> list[TaskProgressRecord]` (ordered by seq); `TaskProgressPayload.kind: str = "text"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
async def test_append_and_list_progress(tmp_path):
    from daemon.registry import AgentRegistry
    reg = AgentRegistry(str(tmp_path / "t.db"))
    await reg.initialize()
    s1 = await reg.append_progress("t1", "milestone", "worktree created")
    s2 = await reg.append_progress("t1", "tool", "tool: Edit")
    assert (s1, s2) == (1, 2)
    items = await reg.list_progress("t1")
    assert [i.seq for i in items] == [1, 2]
    assert items[0].kind == "milestone"
    assert items[1].message == "tool: Edit"
    # isolation between tasks
    assert await reg.list_progress("other") == []
    await reg.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py::test_append_and_list_progress -v`
Expected: FAIL with `AttributeError: 'AgentRegistry' object has no attribute 'append_progress'`

- [ ] **Step 3: Add the models**

In `daemon/models.py`, replace the existing `TaskProgressPayload` (lines 208-209) with:

```python
class TaskProgressPayload(BaseModel):
    message: str
    kind: str = "text"  # milestone | tool | text | error | summary


class TaskProgressRecord(BaseModel):
    task_id: str
    seq: int
    kind: str
    message: str
    ts: str
```

- [ ] **Step 4: Create the table**

In `daemon/registry.py`, inside `initialize()`, after the `idx_agent_tasks_project_status` index (line 88) and before `initialize()` finishes (keep it next to the other `CREATE TABLE` calls), add:

```python
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
```

- [ ] **Step 5: Add the registry methods**

In `daemon/registry.py`, add the `TaskProgressRecord` import to the existing `from daemon.models import (...)` block, then add these methods after `update_agent_task` (after line 314):

```python
    async def append_progress(self, task_id: str, kind: str, message: str) -> int:
        cursor = await self.db.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM task_progress WHERE task_id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        seq = (row["m"] if row else 0) + 1
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
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_registry.py::test_append_and_list_progress -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add daemon/models.py daemon/registry.py tests/test_registry.py
git commit -m "feat: persist task progress lines in a task_progress table"
```

---

## Task 2: Progress API — persist on POST, expose history via GET

**Files:**
- Modify: `daemon/api.py:660-665` (`task_progress` handler) and add a `GET` handler after it
- Test: `tests/test_api.py` (update `test_task_progress_endpoint_emits_event`; add a persistence test)

**Interfaces:**
- Consumes: `registry.append_progress`, `registry.list_progress`, `TaskProgressPayload.kind` (Task 1).
- Produces: `POST /api/projects/{id}/tasks/{tid}/progress` now persists and emits `task:progress` with `{id, seq, kind, message}`; `GET /api/projects/{id}/tasks/{tid}/progress` returns `{items: [TaskProgressRecord...]}`.

- [ ] **Step 1: Update the existing event test + add a persistence test**

In `tests/test_api.py`, change the final assertion of `test_task_progress_endpoint_emits_event` (lines 507-509) to the new event shape:

```python
        ev = api_module.router.events.get_nowait()
        assert ev.event == "task:progress"
        assert ev.data == {
            "id": task_id, "seq": 1, "kind": "text", "message": "running tool: Edit",
        }
```

Then add a new test:

```python
def test_task_progress_persisted_and_listed(client):
    res = client.post("/api/projects/noor/tasks",
                      json={"project": "noor", "title": "T", "instruction": "do"})
    task_id = res.json()["id"]
    client.post(f"/api/projects/noor/tasks/{task_id}/progress",
                json={"message": "worktree created", "kind": "milestone"})
    client.post(f"/api/projects/noor/tasks/{task_id}/progress",
                json={"message": "tool: Edit"})
    res = client.get(f"/api/projects/noor/tasks/{task_id}/progress")
    assert res.status_code == 200
    items = res.json()["items"]
    assert [i["seq"] for i in items] == [1, 2]
    assert items[0]["kind"] == "milestone"
    assert items[0]["message"] == "worktree created"
    assert items[1]["kind"] == "text"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py::test_task_progress_endpoint_emits_event tests/test_api.py::test_task_progress_persisted_and_listed -v`
Expected: FAIL (`test_task_progress_persisted_and_listed` 404/no GET route; event test asserts old shape)

- [ ] **Step 3: Implement persistence + history**

In `daemon/api.py`, replace the `task_progress` handler (lines 660-665) with:

```python
@app.post("/api/projects/{project_id}/tasks/{task_id}/progress")
async def task_progress(project_id: str, task_id: str, payload: TaskProgressPayload):
    """Persist a progress line and relay it to WebSocket clients."""
    seq = await registry.append_progress(task_id, payload.kind, payload.message)
    if router:
        await router._emit_event("task:progress", project_id, {
            "id": task_id, "seq": seq, "kind": payload.kind, "message": payload.message,
        })
    return {"ok": True, "seq": seq}


@app.get("/api/projects/{project_id}/tasks/{task_id}/progress")
async def get_task_progress(project_id: str, task_id: str):
    """Return the persisted progress transcript for a task, ordered by seq."""
    items = await registry.list_progress(task_id)
    return {"items": [i.model_dump() for i in items]}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api.py::test_task_progress_endpoint_emits_event tests/test_api.py::test_task_progress_persisted_and_listed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat: persist task progress and expose GET transcript endpoint"
```

---

## Task 3: WorkerSupervisor — spawn/track/stop one-shot workers

**Files:**
- Create: `daemon/supervisor.py`
- Test: `tests/test_supervisor.py`

**Interfaces:**
- Produces: `WorkerSupervisor` with `spawn(project, agent, project_path, task_id, max_budget_usd=5.0) -> None` (no-op if already running), `is_running(task_id) -> bool` (lazily reaps exited procs), `running_ids() -> list[str]`, `stop(task_id) -> bool` (True if a live proc was terminated). Spawns `[sys.executable, "-m", "daemon.main", "worker", "--once", "--task", task_id, "--project", project, "--agent", agent, "--project-path", project_path, "--max-budget-usd", str(...)]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_supervisor.py`:

```python
import daemon.supervisor as sup_mod
from daemon.supervisor import WorkerSupervisor


class _FakePopen:
    def __init__(self, cmd):
        self.cmd = cmd
        self._returncode = None  # None = still running
        self.terminated = False
        self.killed = False
    def poll(self):
        return self._returncode
    def terminate(self):
        self.terminated = True
        self._returncode = -15
    def kill(self):
        self.killed = True
        self._returncode = -9
    def wait(self, timeout=None):
        return self._returncode


def _patch_popen(monkeypatch, sink=None):
    def _factory(cmd, *a, **k):
        p = _FakePopen(cmd)
        if sink is not None:
            sink.append(p)
        return p
    monkeypatch.setattr(sup_mod.subprocess, "Popen", _factory)


def test_spawn_tracks_process_and_builds_once_command(monkeypatch):
    created = []
    _patch_popen(monkeypatch, created)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1", 5.0)
    assert s.is_running("t1") is True
    assert s.running_ids() == ["t1"]
    cmd = created[0].cmd
    assert cmd[1:4] == ["-m", "daemon.main", "worker"]
    assert "--once" in cmd
    assert cmd[cmd.index("--task") + 1] == "t1"
    assert cmd[cmd.index("--project-path") + 1] == "/tmp/noor"


def test_spawn_idempotent_while_running(monkeypatch):
    _patch_popen(monkeypatch)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    first = s._procs["t1"]
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    assert s._procs["t1"] is first


def test_is_running_reaps_exited(monkeypatch):
    _patch_popen(monkeypatch)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    s._procs["t1"]._returncode = 0  # simulate exit
    assert s.is_running("t1") is False
    assert "t1" not in s._procs
    assert s.running_ids() == []


def test_stop_terminates_live_process(monkeypatch):
    _patch_popen(monkeypatch)
    s = WorkerSupervisor()
    s.spawn("noor", "claude-code", "/tmp/noor", "t1")
    proc = s._procs["t1"]
    assert s.stop("t1") is True
    assert proc.terminated is True
    assert s.is_running("t1") is False
    assert s.stop("t1") is False  # nothing left to stop
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_supervisor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.supervisor'`

- [ ] **Step 3: Implement the supervisor**

Create `daemon/supervisor.py`:

```python
"""Worker supervisor — spawns and tracks one-shot `loom worker` subprocesses.

One subprocess per task (V1): the daemon launches a worker that processes a
single Running task and exits. The supervisor keeps the live handle so the UI
can show "a worker is attached" and offer Stop. Exited processes are reaped
lazily on inspection (no background task), which keeps test mode side-effect free.
"""

from __future__ import annotations

import logging
import subprocess
import sys

logger = logging.getLogger("loom.supervisor")


class WorkerSupervisor:
    def __init__(self) -> None:
        self._procs: dict[str, subprocess.Popen] = {}

    def spawn(self, project: str, agent: str, project_path: str,
              task_id: str, max_budget_usd: float = 5.0) -> None:
        """Launch a one-shot worker for a single task. No-op if already live."""
        if self.is_running(task_id):
            return
        cmd = [
            sys.executable, "-m", "daemon.main", "worker",
            "--once", "--task", task_id,
            "--project", project, "--agent", agent,
            "--project-path", project_path,
            "--max-budget-usd", str(max_budget_usd),
        ]
        logger.info("spawning one-shot worker for task %s", task_id)
        self._procs[task_id] = subprocess.Popen(cmd)

    def is_running(self, task_id: str) -> bool:
        proc = self._procs.get(task_id)
        if proc is None:
            return False
        if proc.poll() is None:
            return True
        self._procs.pop(task_id, None)  # exited — reap
        return False

    def running_ids(self) -> list[str]:
        return [tid for tid in list(self._procs) if self.is_running(tid)]

    def stop(self, task_id: str) -> bool:
        """Terminate a live worker. Returns True if one was running."""
        proc = self._procs.get(task_id)
        if proc is None or proc.poll() is not None:
            self._procs.pop(task_id, None)
            return False
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._procs.pop(task_id, None)
        return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_supervisor.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add daemon/supervisor.py tests/test_supervisor.py
git commit -m "feat: add WorkerSupervisor to spawn and track one-shot workers"
```

---

## Task 4: Worker one-shot mode + progress milestones

**Files:**
- Modify: `daemon/worker.py` — `_post_progress` (line 141), `process_task` (line 160), add `run_once`
- Modify: `daemon/main.py` — `worker` subparser (line 166) and `cmd_worker` (line 69)
- Modify: `tests/test_worker.py` — `_CaptureWorker._post_progress` (line 21); add one-shot + milestone tests

**Interfaces:**
- Consumes: `POST /tasks/{id}/progress` with `{message, kind}` (Task 2).
- Produces: `Worker.run_once(task_id: str) -> None`; `Worker._post_progress(task_id, message, kind="text")`; CLI `loom worker --once --task <id>`. `process_task` emits milestones (`kind="milestone"`), the final summary (`kind="summary"`), and errors (`kind="error"`).

- [ ] **Step 1: Update the capture helper and write failing tests**

In `tests/test_worker.py`, change `_CaptureWorker._post_progress` (lines 21-22) to accept `kind` and store a 3-tuple:

```python
    def _post_progress(self, task_id, message, kind="text"):
        self.progress.append((task_id, kind, message))
```

Then add these tests:

```python
def test_run_once_processes_matching_task(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x")
    monkeypatch.setattr(w, "ensure_registered", lambda: None)
    monkeypatch.setattr(w, "_get_running_tasks", lambda: [
        {"id": "a", "assignee": "claude-code-noor", "title": "A", "instruction": "x", "result": None},
    ])
    processed = []
    monkeypatch.setattr(w, "process_task", lambda task: processed.append(task["id"]))
    w.run_once("a")
    assert processed == ["a"]


def test_run_once_no_match_is_noop(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x")
    monkeypatch.setattr(w, "ensure_registered", lambda: None)
    monkeypatch.setattr(w, "_get_running_tasks", lambda: [])
    def _boom(task):
        raise AssertionError("should not process anything")
    monkeypatch.setattr(w, "process_task", _boom)
    w.run_once("missing")  # returns cleanly


def test_process_task_posts_milestones_and_summary(monkeypatch):
    w = _CaptureWorker(project="noor", agent="claude-code", project_path="/tmp/noor", base_url="http://x")
    _patch_git_and_claude(monkeypatch, ClaudeResult("done text", "sess-1", False))
    w.process_task({"id": "t1", "title": "T", "instruction": "x",
                    "acceptance_criteria": "", "result": None})
    kinds = [k for (_tid, k, _m) in w.progress]
    assert "milestone" in kinds
    assert "summary" in kinds
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker.py::test_run_once_processes_matching_task tests/test_worker.py::test_process_task_posts_milestones_and_summary -v`
Expected: FAIL (`run_once` missing; no milestone/summary posts)

- [ ] **Step 3: Add `kind` to `_post_progress`**

In `daemon/worker.py`, replace `_post_progress` (lines 141-146) with:

```python
    def _post_progress(self, task_id: str, message: str, kind: str = "text") -> None:
        try:
            self._api("POST", f"/api/projects/{self.project}/tasks/{task_id}/progress",
                      {"message": message, "kind": kind})
        except Exception:
            pass  # progress is best-effort
```

- [ ] **Step 4: Add milestone/summary/error posts in `process_task`**

In `daemon/worker.py` `process_task`, make these edits:

(a) In the worktree-failure `except RuntimeError` block (lines 173-179), add a progress post before the `_patch_task(...)`:

```python
        except RuntimeError as exc:
            self._post_progress(task_id, f"Worktree failed: {exc}", kind="error")
            self._patch_task(task_id, {
                "status": "blocked",
                "result": json.dumps({"branch": branch, "base_branch": "unknown",
                                      "error": f"worktree failed: {exc}"}),
            })
            return
```

(b) After `self._patch_task(task_id, {"workspace_path": workspace})` (line 183), add:

```python
        self._post_progress(task_id, f"Created worktree on {branch}", kind="milestone")
```

(c) Change the `run_claude` call (lines 196-199) so the stream callback tags tool lines and add an "Agent started" milestone immediately before it:

```python
        self._post_progress(task_id, "Agent started", kind="milestone")
        result = run_claude(
            prompt, cwd=workspace, model=self.model, max_budget_usd=self.max_budget_usd,
            resume=resume,
            on_progress=lambda line: self._post_progress(
                task_id, line, kind="tool" if line.startswith("tool:") else "text"),
        )
```

(d) In the error branch (lines 204-210), add an error post before the patch:

```python
        if result.is_error:
            meta["error"] = result.text or "claude reported an error"
            self._post_progress(task_id, meta["error"], kind="error")
            self._patch_task(task_id, {
                "status": "blocked", "result": json.dumps(meta),
                "workspace_path": workspace,
            })
            return
```

(e) In the success path (after line 212 `commit_all(...)`, before/with the final patch), add a summary + completion milestone:

```python
        commit_all(workspace, f"loom task {task_id}: {title}")
        self._write_finding(task_id, title, result.text)
        self._post_progress(task_id, result.text or "(no output)", kind="summary")
        self._post_progress(task_id, "Task complete", kind="milestone")
        self._patch_task(task_id, {
            "status": "done", "result": json.dumps(meta),
            "workspace_path": workspace,
        })
```

- [ ] **Step 5: Add `run_once`**

In `daemon/worker.py`, add this method to `Worker` (e.g. after `poll_once`, line 226):

```python
    def run_once(self, task_id: str) -> None:
        """Process a single Running task by id, then return (no poll loop)."""
        self.ensure_registered()
        task = next(
            (t for t in self._get_running_tasks() if t.get("id") == task_id), None
        )
        if task is None:
            logger.info("task %s not in Running; nothing to do", task_id)
            return
        self.process_task(task)
```

- [ ] **Step 6: Wire the CLI flags**

In `daemon/main.py`, add to the `worker` subparser (after line 173):

```python
    worker_p.add_argument("--once", action="store_true",
                          help="Process a single task (with --task) and exit")
    worker_p.add_argument("--task", default=None,
                          help="Task id to process when --once is set")
```

Then replace `cmd_worker` (lines 69-84) with:

```python
def cmd_worker(args):
    """Run a Loom worker that executes Running tasks with Claude Code."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    from daemon.worker import Worker
    w = Worker(
        project=args.project,
        agent=args.agent,
        project_path=os.path.expanduser(args.project_path),
        base_url=args.base_url,
        model=args.model,
        max_budget_usd=args.max_budget_usd,
        poll_interval=args.poll,
    )
    if args.once:
        if not args.task:
            raise SystemExit("--once requires --task <id>")
        w.run_once(args.task)
    else:
        w.run()
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_worker.py -v`
Expected: PASS (all worker tests, including the 3 new ones)

- [ ] **Step 8: Commit**

```bash
git add daemon/worker.py daemon/main.py tests/test_worker.py
git commit -m "feat: one-shot worker mode (--once --task) with progress milestones"
```

---

## Task 5: Spawn hook + worker control/status endpoints

**Files:**
- Modify: `daemon/api.py` — imports (line 14-24), globals (line 29-40), lifespan (line 51, 64-67), `update_agent_task` (line 650-657), add `_start_worker_for` + 4 endpoints near the task routes
- Modify: `tests/test_api.py` — fixture (add `supervisor=None`); add fake supervisor + 4 tests

**Interfaces:**
- Consumes: `WorkerSupervisor` (Task 3); `registry.get_project`, `registry.get_agent_task`, `registry.update_agent_task`.
- Produces: auto-spawn on PATCH→running; `POST /tasks/{id}/worker/start`, `POST /tasks/{id}/worker/stop`, `GET /projects/{id}/workers`; WS events `worker:started`, `worker:exited`.

- [ ] **Step 1: Make the fixture supervisor-safe + write failing tests**

In `tests/test_api.py` `client` fixture, after `api_module.watcher = None` (line 44) add:

```python
    api_module.supervisor = None
```

Add a fake supervisor class near the top of the test module (after the imports, ~line 20):

```python
class _FakeSupervisor:
    def __init__(self):
        self.spawned = []
        self._running = set()
    def spawn(self, project, agent, project_path, task_id, max_budget_usd=5.0):
        self.spawned.append((project, agent, project_path, task_id))
        self._running.add(task_id)
    def is_running(self, task_id):
        return task_id in self._running
    def running_ids(self):
        return list(self._running)
    def stop(self, task_id):
        was = task_id in self._running
        self._running.discard(task_id)
        return was
```

Add the tests:

```python
def test_patch_to_running_spawns_worker_once(client):
    import daemon.api as api_module
    from daemon.router import Router
    api_module.router = Router(api_module.registry, api_module.graph_engine)
    sup = _FakeSupervisor()
    api_module.supervisor = sup
    try:
        res = client.post("/api/projects/noor/tasks",
                          json={"project": "noor", "title": "T", "instruction": "x"})
        task_id = res.json()["id"]
        client.patch(f"/api/projects/noor/tasks/{task_id}",
                     json={"status": "running", "assignee": "claude-code-noor"})
        assert len(sup.spawned) == 1
        proj, agent, path, tid = sup.spawned[0]
        assert (proj, agent, tid) == ("noor", "claude-code", task_id)
        assert path.endswith("/noor")
        # idempotent: a second PATCH while running does not re-spawn
        client.patch(f"/api/projects/noor/tasks/{task_id}", json={"status": "running"})
        assert len(sup.spawned) == 1
    finally:
        api_module.router = None
        api_module.supervisor = None


def test_patch_to_running_without_assignee_does_not_spawn(client):
    import daemon.api as api_module
    sup = _FakeSupervisor()
    api_module.supervisor = sup
    try:
        res = client.post("/api/projects/noor/tasks",
                          json={"project": "noor", "title": "T", "instruction": "x"})
        task_id = res.json()["id"]
        client.patch(f"/api/projects/noor/tasks/{task_id}", json={"status": "running"})
        assert sup.spawned == []
    finally:
        api_module.supervisor = None


def test_worker_stop_blocks_task(client):
    import daemon.api as api_module
    from daemon.router import Router
    api_module.router = Router(api_module.registry, api_module.graph_engine)
    sup = _FakeSupervisor()
    api_module.supervisor = sup
    try:
        res = client.post("/api/projects/noor/tasks",
                          json={"project": "noor", "title": "T", "instruction": "x"})
        task_id = res.json()["id"]
        client.patch(f"/api/projects/noor/tasks/{task_id}",
                     json={"status": "running", "assignee": "claude-code-noor"})
        res = client.post(f"/api/projects/noor/tasks/{task_id}/worker/stop")
        assert res.status_code == 200
        assert res.json()["stopped"] is True
        listing = client.get("/api/projects/noor/tasks").json()
        t = next(x for x in listing if x["id"] == task_id)
        assert t["status"] == "blocked"
    finally:
        api_module.router = None
        api_module.supervisor = None


def test_list_workers_returns_running_ids(client):
    import daemon.api as api_module
    sup = _FakeSupervisor()
    sup._running.add("abc")
    api_module.supervisor = sup
    try:
        res = client.get("/api/projects/noor/workers")
        assert res.json() == {"running": ["abc"]}
    finally:
        api_module.supervisor = None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py::test_patch_to_running_spawns_worker_once tests/test_api.py::test_worker_stop_blocks_task tests/test_api.py::test_list_workers_returns_running_ids -v`
Expected: FAIL (no spawn hook; `/worker/stop` + `/workers` routes 404)

- [ ] **Step 3: Register the supervisor global**

In `daemon/api.py`: add the import after line 19 (`from daemon.snapshots import SnapshotManager`):

```python
from daemon.supervisor import WorkerSupervisor
```

Add a constant + global after `connected_clients` (line 40):

```python
WORKER_MAX_BUDGET_USD = 5.0
supervisor: Optional[WorkerSupervisor] = None
```

In `lifespan`, add `supervisor` to the `global` declaration (line 51), and after the `snapshot_manager` init (lines 66-67) add:

```python
    if not test_mode and supervisor is None:
        supervisor = WorkerSupervisor()
```

- [ ] **Step 4: Add the spawn helper + hook**

In `daemon/api.py`, add this helper above the task routes (e.g. just before line 613 `create_agent_task`):

```python
async def _start_worker_for(project_id: str, task: AgentTaskRecord) -> bool:
    """Spawn a one-shot worker for a Running task. Returns True if spawned."""
    if supervisor is None or not task.assignee:
        return False
    project = await registry.get_project(project_id)
    if project is None:
        return False
    agent = task.assignee.removesuffix(f"-{project_id}")
    supervisor.spawn(project_id, agent, project.project_path, task.id,
                     WORKER_MAX_BUDGET_USD)
    if router:
        await router._emit_event("worker:started", project_id, {"id": task.id})
    return True
```

In `update_agent_task`, after the `task:updated` emit (line 651) and before the `DONE`-promotion block (line 652), add:

```python
    if (supervisor is not None and payload.status == AgentTaskStatus.RUNNING
            and updated.assignee and not supervisor.is_running(task_id)):
        await _start_worker_for(project_id, updated)
```

- [ ] **Step 5: Add the worker control + status endpoints**

In `daemon/api.py`, after the `get_task_progress` handler (added in Task 2), add:

```python
@app.post("/api/projects/{project_id}/tasks/{task_id}/worker/start")
async def worker_start(project_id: str, task_id: str):
    """Manually (re)launch a one-shot worker for a task with an assignee."""
    if supervisor is None:
        raise HTTPException(status_code=503, detail="Worker supervisor unavailable")
    record = await registry.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    if not record.assignee:
        raise HTTPException(status_code=400, detail="Task has no assignee")
    if supervisor.is_running(task_id):
        return {"started": False, "running": True}
    if not await _start_worker_for(project_id, record):
        raise HTTPException(status_code=400, detail="Could not start worker")
    return {"started": True, "running": True}


@app.post("/api/projects/{project_id}/tasks/{task_id}/worker/stop")
async def worker_stop(project_id: str, task_id: str):
    """Stop a live worker and mark its task blocked (cancelled by user)."""
    if supervisor is None:
        raise HTTPException(status_code=503, detail="Worker supervisor unavailable")
    was_running = supervisor.stop(task_id)
    record = await registry.get_agent_task(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Agent task not found")
    try:
        meta = _json.loads(record.result or "{}")
    except (ValueError, TypeError):
        meta = {}
    meta["cancelled"] = True
    await registry.update_agent_task(task_id, status=AgentTaskStatus.BLOCKED,
                                     result=_json.dumps(meta))
    updated = await registry.get_agent_task(task_id)
    if router:
        await router._emit_event("worker:exited", project_id, {"id": task_id})
        if updated:
            await router._emit_event("task:updated", project_id, updated.model_dump())
    return {"stopped": was_running}


@app.get("/api/projects/{project_id}/workers")
async def list_workers(project_id: str):
    """Task ids that currently have a live worker process."""
    if supervisor is None:
        return {"running": []}
    return {"running": supervisor.running_ids()}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v`
Expected: PASS (new tests pass; existing running-status tests at lines 244/320/445 still pass because the fixture sets `supervisor=None`)

- [ ] **Step 7: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat: auto-spawn worker on Running + worker start/stop/list endpoints"
```

---

## Task 6: Dashboard API client — progress + worker calls

**Files:**
- Modify: `dashboard/lib/api.ts` (add type + 4 functions, e.g. after `mergeTask`, line 309)

**Interfaces:**
- Produces: `TaskProgressItem`; `getTaskProgress(projectId, taskId) -> {items: TaskProgressItem[]}`; `listWorkers(projectId) -> {running: string[]}`; `startWorker(projectId, taskId) -> {started: boolean; running: boolean}`; `stopWorker(projectId, taskId) -> {stopped: boolean}`.

- [ ] **Step 1: Add the type and functions**

In `dashboard/lib/api.ts`, after `mergeTask` (line 309), add:

```typescript
export interface TaskProgressItem {
  task_id: string;
  seq: number;
  kind: string; // milestone | tool | text | error | summary
  message: string;
  ts: string;
}

export async function getTaskProgress(
  projectId: string,
  taskId: string,
): Promise<{ items: TaskProgressItem[] }> {
  return fetchApi(`/api/projects/${projectId}/tasks/${taskId}/progress`);
}

export async function listWorkers(projectId: string): Promise<{ running: string[] }> {
  return fetchApi(`/api/projects/${projectId}/workers`);
}

export async function startWorker(
  projectId: string,
  taskId: string,
): Promise<{ started: boolean; running: boolean }> {
  const res = await fetch(
    `${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/worker/start`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export async function stopWorker(
  projectId: string,
  taskId: string,
): Promise<{ stopped: boolean }> {
  const res = await fetch(
    `${BASE_URL}/api/projects/${projectId}/tasks/${taskId}/worker/stop`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}
```

- [ ] **Step 2: Type-check**

Run: `cd dashboard && npm run lint && npm run build`
Expected: lint clean, build succeeds (no type errors).

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/api.ts
git commit -m "feat: dashboard client for task progress and worker control"
```

---

## Task 7: Tasks page — track worker liveness

**Files:**
- Modify: `dashboard/app/[locale]/projects/[id]/tasks/page.tsx`

**Interfaces:**
- Consumes: `listWorkers` (Task 6); WS events `worker:started`/`worker:exited`/`task:updated`.
- Produces: a `workerIds: Set<string>` passed to the drawer as `workerRunning`.

- [ ] **Step 1: Import the new call and add worker-id state**

In `dashboard/app/[locale]/projects/[id]/tasks/page.tsx`, extend the api import (lines 8-11) to include `listWorkers`:

```tsx
import {
  listAgentTasks, getProject, updateAgentTask, listWorkers,
  type AgentTask, type AgentTaskStatus, type AgentInfo,
} from "@/lib/api";
```

Add state after `selected` (line 25):

```tsx
  const [workerIds, setWorkerIds] = useState<Set<string>>(new Set());
```

- [ ] **Step 2: Seed worker ids in `loadData`**

Replace `loadData` (lines 28-38) with:

```tsx
  const loadData = useCallback(async () => {
    try {
      const [taskList, project, workers] = await Promise.all([
        listAgentTasks(id),
        getProject(id),
        listWorkers(id),
      ]);
      setTasks(taskList);
      setAgents(project.agents || []);
      setWorkerIds(new Set(workers.running));
    } catch {
      // no tasks yet
    } finally {
      setLoading(false);
    }
  }, [id]);
```

- [ ] **Step 3: Maintain worker ids from WS events**

Replace the WS subscribe effect (lines 47-59) with:

```tsx
  useEffect(() => {
    const upsert = (task: AgentTask) =>
      setTasks((prev) => {
        const i = prev.findIndex((x) => x.id === task.id);
        if (i === -1) return [task, ...prev];
        const next = [...prev]; next[i] = task; return next;
      });
    return subscribe(`project:${id}`, (event) => {
      if (event.event === "task:created" || event.event === "task:updated") {
        const task = event.data as unknown as AgentTask;
        upsert(task);
        if (event.event === "task:updated" &&
            (task.status === "done" || task.status === "blocked")) {
          setWorkerIds((prev) => {
            const n = new Set(prev); n.delete(task.id); return n;
          });
        }
      } else if (event.event === "worker:started") {
        const tid = (event.data as { id: string }).id;
        setWorkerIds((prev) => new Set(prev).add(tid));
      } else if (event.event === "worker:exited") {
        const tid = (event.data as { id: string }).id;
        setWorkerIds((prev) => {
          const n = new Set(prev); n.delete(tid); return n;
        });
      }
    });
  }, [id, subscribe]);
```

- [ ] **Step 4: Pass liveness to the drawer**

Replace the `<TaskDetailDrawer .../>` block (lines 102-109) with:

```tsx
      <TaskDetailDrawer
        key={selected?.id ?? "none"}
        task={selected}
        projectId={id}
        agents={agents}
        workerRunning={selected ? workerIds.has(selected.id) : false}
        onClose={() => setSelected(null)}
        onChanged={loadData}
      />
```

- [ ] **Step 5: Type-check**

Run: `cd dashboard && npm run lint && npm run build`
Expected: build fails ONLY on the not-yet-added `workerRunning` prop (resolved in Task 8). If you implement Task 8 first this passes; otherwise this is the expected intermediate state — proceed to Task 8 before the final build gate.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/\[locale\]/projects/\[id\]/tasks/page.tsx
git commit -m "feat: track live worker ids on the tasks page"
```

---

## Task 8: Task detail drawer → live chat window

**Files:**
- Modify: `dashboard/components/task-detail-drawer.tsx` (full rewrite below)
- Modify: `dashboard/messages/en.json` (TaskDetail block, lines 221-232)
- Modify: `dashboard/messages/ar.json` (TaskDetail block, mirror)

**Interfaces:**
- Consumes: `getTaskProgress`, `startWorker`, `stopWorker`, `TaskProgressItem` (Task 6); `useWebSocket().subscribe` (`task:progress`); `workerRunning` prop (Task 7).
- Produces: the chat-window drawer.

- [ ] **Step 1: Add i18n keys (both locales)**

In `dashboard/messages/en.json`, replace the `TaskDetail` block (lines 221-232) with:

```json
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
    "mergeConflict": "Merge failed — resolve conflicts manually.",
    "activity": "Activity",
    "noActivity": "No activity yet.",
    "workerRunning": "Worker running",
    "workerIdle": "No worker",
    "run": "Run",
    "stop": "Stop",
    "noWorkerTitle": "Queued, but nothing is running it",
    "noWorkerBody": "This task is in Running, but no worker is attached. Click Run to start one."
  }
```

In `dashboard/messages/ar.json`, replace its `TaskDetail` block with the same keys, Arabic values:

```json
  "TaskDetail": {
    "status": "الحالة",
    "assignee": "المسؤول",
    "unassigned": "غير معيّن",
    "instruction": "التعليمات",
    "acceptanceCriteria": "معايير القبول",
    "result": "النتيجة",
    "diff": "التغييرات",
    "merge": "دمج",
    "mergeOk": "تم الدمج في فرع المشروع.",
    "mergeConflict": "فشل الدمج — قم بحل التعارضات يدويًا.",
    "activity": "النشاط",
    "noActivity": "لا يوجد نشاط بعد.",
    "workerRunning": "العامل قيد التشغيل",
    "workerIdle": "لا يوجد عامل",
    "run": "تشغيل",
    "stop": "إيقاف",
    "noWorkerTitle": "في قائمة الانتظار، لكن لا شيء يُنفّذها",
    "noWorkerBody": "هذه المهمة في حالة التشغيل، لكن لا يوجد عامل متصل. اضغط تشغيل لبدء واحد."
  }
```

> If the `TaskDetail` block is not the last key in a file, keep the trailing comma after the closing brace. Validate with `node -e "require('./dashboard/messages/en.json'); require('./dashboard/messages/ar.json')"`.

- [ ] **Step 2: Rewrite the drawer as a chat window**

Replace the entire contents of `dashboard/components/task-detail-drawer.tsx` with:

```tsx
"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { X, GitMerge, Loader2, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWebSocket } from "@/lib/use-websocket";
import {
  getTaskDiff,
  mergeTask,
  updateAgentTask,
  getTaskProgress,
  startWorker,
  stopWorker,
  type AgentTask,
  type AgentInfo,
  type AgentTaskStatus,
  type TaskProgressItem,
} from "@/lib/api";

const STATUSES: AgentTaskStatus[] = [
  "triage", "todo", "ready", "running", "blocked", "done", "archived",
];

interface TaskDetailDrawerProps {
  task: AgentTask | null;
  projectId: string;
  agents: AgentInfo[];
  workerRunning: boolean;
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

const KIND_STYLE: Record<string, string> = {
  milestone: "text-sky-400",
  tool: "text-violet-300",
  text: "text-zinc-300",
  error: "text-red-400",
  summary: "text-emerald-300",
};

export function TaskDetailDrawer({
  task,
  projectId,
  agents,
  workerRunning,
  onClose,
  onChanged,
}: TaskDetailDrawerProps) {
  const t = useTranslations("TaskDetail");
  const { subscribe } = useWebSocket();
  const [diff, setDiff] = useState("");
  const [merging, setMerging] = useState(false);
  const [mergeMsg, setMergeMsg] = useState("");
  const [progress, setProgress] = useState<TaskProgressItem[]>([]);
  const [busy, setBusy] = useState(false);
  const feedRef = useRef<HTMLDivElement>(null);

  // Load diff for completed/blocked tasks.
  useEffect(() => {
    if (!task) return;
    if (task.status === "done" || task.status === "blocked") {
      let cancelled = false;
      getTaskDiff(projectId, task.id)
        .then((d) => { if (!cancelled) setDiff(d.diff); })
        .catch(() => {});
      return () => { cancelled = true; };
    }
  }, [task, projectId]);

  // Load progress history once, then append live events (deduped by seq).
  useEffect(() => {
    if (!task) return;
    const taskId = task.id;
    let cancelled = false;
    getTaskProgress(projectId, taskId)
      .then((p) => { if (!cancelled) setProgress(p.items); })
      .catch(() => {});
    const unsub = subscribe("task:progress", (event) => {
      const d = event.data as { id: string; seq: number; kind: string; message: string };
      if (d.id !== taskId) return;
      setProgress((prev) =>
        prev.some((i) => i.seq === d.seq)
          ? prev
          : [...prev, { task_id: taskId, seq: d.seq, kind: d.kind, message: d.message, ts: "" }],
      );
    });
    return () => { cancelled = true; unsub(); };
  }, [task, projectId, subscribe]);

  // Auto-scroll the feed to the newest line.
  useEffect(() => {
    if (feedRef.current) feedRef.current.scrollTop = feedRef.current.scrollHeight;
  }, [progress]);

  if (!task) return null;

  async function handleMerge() {
    setMerging(true);
    setMergeMsg("");
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
    try {
      await updateAgentTask(projectId, task!.id, { status });
    } catch {
      // ignore — the finally re-syncs from server state
    } finally {
      onChanged();
    }
  }

  async function handleAssignee(assignee: string) {
    try {
      await updateAgentTask(projectId, task!.id, { assignee: assignee || null });
    } catch {
      // ignore
    } finally {
      onChanged();
    }
  }

  async function handleRun() {
    setBusy(true);
    try {
      await startWorker(projectId, task!.id);
    } catch {
      // ignore — WS events re-sync liveness
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  async function handleStop() {
    setBusy(true);
    try {
      await stopWorker(projectId, task!.id);
    } catch {
      // ignore
    } finally {
      setBusy(false);
      onChanged();
    }
  }

  const isDone = task.status === "done";
  const isBlocked = task.status === "blocked";
  const showNoWorker = task.status === "running" && !workerRunning;
  const canRun = !workerRunning && !isDone && !!task.assignee;

  return (
    <div className="fixed inset-y-0 end-0 w-[440px] bg-zinc-950 border-s border-zinc-800 shadow-xl z-50 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-zinc-800">
        <div className="flex items-center gap-2 min-w-0">
          <h3 className="text-sm font-bold text-zinc-100 truncate">{task.title}</h3>
          <span
            className={`shrink-0 inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded ${
              workerRunning ? "bg-amber-500/10 text-amber-400" : "bg-zinc-800 text-zinc-500"
            }`}
          >
            {workerRunning && <Loader2 className="w-2.5 h-2.5 animate-spin" />}
            {workerRunning ? t("workerRunning") : t("workerIdle")}
          </span>
        </div>
        <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex items-center gap-2 px-4 py-2 border-b border-zinc-800">
        {workerRunning ? (
          <Button size="sm" variant="outline" onClick={handleStop} disabled={busy}>
            <Square className="w-3 h-3" />
            <span className="ms-1">{t("stop")}</span>
          </Button>
        ) : (
          <Button size="sm" onClick={handleRun} disabled={busy || !canRun}>
            <Play className="w-3 h-3" />
            <span className="ms-1">{t("run")}</span>
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs">
        {showNoWorker && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-2">
            <p className="text-amber-300 font-medium">{t("noWorkerTitle")}</p>
            <p className="text-amber-200/80 mt-1">{t("noWorkerBody")}</p>
          </div>
        )}

        <div>
          <label htmlFor="task-status" className="text-zinc-500 block mb-1">{t("status")}</label>
          <select
            id="task-status"
            value={task.status}
            onChange={(e) => handleStatus(e.target.value as AgentTaskStatus)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1.5 text-zinc-200"
          >
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div>
          <label htmlFor="task-assignee" className="text-zinc-500 block mb-1">{t("assignee")}</label>
          <select
            id="task-assignee"
            value={task.assignee || ""}
            onChange={(e) => handleAssignee(e.target.value)}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-md px-2 py-1.5 text-zinc-200"
          >
            <option value="">{t("unassigned")}</option>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>{a.agent_name}</option>
            ))}
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

        <div>
          <label className="text-zinc-500 block mb-1">{t("activity")}</label>
          <div
            ref={feedRef}
            className="bg-black/40 border border-zinc-800 rounded p-2 max-h-72 overflow-y-auto space-y-1"
          >
            {progress.length === 0 && (
              <p className="text-[10px] text-zinc-600">{t("noActivity")}</p>
            )}
            {progress.map((item) => (
              <div key={item.seq} className="flex gap-2">
                <span className="text-[9px] text-zinc-700 mt-0.5 shrink-0 w-6 text-end">{item.seq}</span>
                <span className={`text-[11px] whitespace-pre-wrap ${KIND_STYLE[item.kind] || "text-zinc-300"}`}>
                  {item.message}
                </span>
              </div>
            ))}
          </div>
        </div>

        {task.result && (
          <div>
            <label className="text-zinc-500 block mb-1">{t("result")}</label>
            <p className="text-zinc-300 whitespace-pre-wrap">{parseSummary(task.result)}</p>
          </div>
        )}

        {(isDone || isBlocked) && diff && (
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-zinc-500">{t("diff")}</label>
              <Button size="sm" variant="outline" onClick={handleMerge} disabled={merging}>
                {merging ? <Loader2 className="w-3 h-3 animate-spin" /> : <GitMerge className="w-3 h-3" />}
                <span className="ms-1">{t("merge")}</span>
              </Button>
            </div>
            {mergeMsg && <p className="text-[10px] text-zinc-400 mb-1">{mergeMsg}</p>}
            <pre className="bg-black/50 border border-zinc-800 rounded p-2 text-[10px] text-zinc-300 overflow-x-auto max-h-64">
              {diff}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Lint + type-check + build**

Run: `cd dashboard && npm run lint && npm run build`
Expected: lint clean, build succeeds (the `workerRunning` prop from Task 7 now resolves).

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/task-detail-drawer.tsx dashboard/messages/en.json dashboard/messages/ar.json
git commit -m "feat: task detail chat window with worker status and Run/Stop"
```

---

## Task 9: End-to-end manual verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole backend suite**

Run: `pytest tests/ -v`
Expected: all green (including pre-existing tests).

- [ ] **Step 2: Smoke test the daemon contract**

Run: `bash scripts/smoke-test.sh`
Expected: passes (daemon boots, agent registers, API responds).

- [ ] **Step 3: Live walkthrough**

1. Start the daemon: `loom --port 8472`.
2. Start the dashboard: `cd dashboard && npm run dev`; open a project's **Tasks** tab.
3. Create a task, assign it to an agent whose project path is a real git repo, drag it to **Running**.
4. Open the task → confirm: the **Worker running** pill appears, the **Activity** feed streams milestones ("Created worktree…", "Agent started", tool lines), and on completion the card moves to **Done** with a diff + Merge.
5. Reload the page, reopen the task → confirm the transcript **persists** (loaded from `GET …/progress`).
6. Drag a task to Running for an agent with **no live worker scenario** (e.g. stop the daemon's child by clicking **Stop** mid-run) → confirm the **"Queued, but nothing is running it"** banner + a working **Run** button.

- [ ] **Step 4: Commit any fixes, then finish the branch**

Use superpowers:finishing-a-development-branch to open a PR or merge `feat/live-task-execution-view`.

---

## Coverage check (self-review)

- Spec "persist progress" → Tasks 1-2. "WorkerSupervisor" → Task 3. "worker one-shot mode + milestones" → Task 4. "spawn hook + control/status endpoints" → Task 5. "dashboard client" → Task 6. "worker-liveness tracking" → Task 7. "chat window + banner + i18n" → Task 8. "error handling (stop→blocked, orphan recovery)" → Task 5 stop endpoint + Task 4 resume path. "testing strategy" → Tasks 1-5 pytest, Task 9 manual.
- The one spec item intentionally deferred: per-card live dot on the board (spec "Out of Scope / Future"). Not implemented here.
