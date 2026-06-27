# Multi-Agent Worker Runners Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the dashboard's "Run" button actually execute non-Claude agents (hermes, codex, gemini-cli, copilot-cli, aider) by giving the loom worker a per-agent runner registry.

**Architecture:** A new declarative registry module (`daemon/runners.py`) maps each agent to how its CLI is invoked headlessly and how its result is read. `daemon/worker.py` gains a `run_agent()` dispatcher (Claude keeps its existing `run_claude` stream-json path; everyone else uses a generic stdout runner). `daemon/api.py` derives the spawn gate from the registry and exposes the runnable set, and the dashboard gates the Run button on it.

**Tech Stack:** Python 3 + FastAPI + pytest (daemon); Next.js 16 + React 19 + next-intl (dashboard).

## Global Constraints

- Keep `daemon/worker.py`'s `run_claude` function and a `ClaudeResult` name importable from `daemon.worker` — `tests/test_worker.py` patches `worker_mod.run_claude` and imports `ClaudeResult`. Do not break these.
- Registry keys are **canonical agent names** matching `daemon/known_agents.py` (`claude-code`, `hermes`, `codex`, `gemini-cli`, `copilot-cli`, `aider`) and the suffix-stripped assignee used in `daemon/api.py:_route_task_execution` (`assignee.removesuffix(f"-{project_id}")`).
- Daemon test command: `pytest tests/ -v` (asyncio_mode=auto, no extra config).
- Dashboard has no unit-test runner — verify frontend tasks with `npm run lint` and `npm run build` (run from `dashboard/`), plus the manual check noted in the task.
- Add every new UI string to **both** `dashboard/messages/en.json` and `dashboard/messages/ar.json`.
- No new budget/timeout cap is in scope (accepted residual risk per the spec).

## File Structure

- **Create** `daemon/runners.py` — `AgentResult`, `RunnerSpec`, the `RUNNERS` registry, `runnable_agents()`, and the generic `run_stdout()` runner. Pure module, no dependency on `daemon.worker` (avoids a cycle).
- **Modify** `daemon/worker.py` — alias `ClaudeResult = AgentResult`, add `run_agent()`, route `process_task` through it.
- **Modify** `daemon/api.py` — derive `LOOM_WORKER_AGENTS` from the registry; add `GET /api/agents/runnable`.
- **Modify** `dashboard/lib/api.ts` — add `listRunnableAgents()`.
- **Modify** `dashboard/messages/{en,ar}.json` — external-agent strings.
- **Modify** `dashboard/app/[locale]/projects/[id]/tasks/page.tsx` — fetch runnable set, derive `assigneeRunnable`, pass to drawer.
- **Modify** `dashboard/components/task-detail-drawer.tsx` — gate Run on `assigneeRunnable`; show an external-agent note.
- **Create** `tests/test_runners.py`; **Modify** `tests/test_worker.py`, `tests/test_api.py`.

---

### Task 1: Runner registry + generic stdout runner

**Files:**
- Create: `daemon/runners.py`
- Test: `tests/test_runners.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `AgentResult(text: str, session_id: str | None, is_error: bool)` (dataclass)
  - `RunnerSpec(binary: str, mode: str, build_argv: Callable[[str], list[str]] | None, streams_progress: bool, supports_resume: bool, supports_budget: bool)`
  - `RUNNERS: dict[str, RunnerSpec]`
  - `runnable_agents() -> set[str]`
  - `run_stdout(spec: RunnerSpec, prompt: str, cwd: str, on_progress: Callable[[str], None] | None = None) -> AgentResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_runners.py`:

```python
import pytest
from daemon.runners import (
    AgentResult, RunnerSpec, RUNNERS, runnable_agents, run_stdout,
)


def test_runnable_agents_is_registry_keys():
    assert runnable_agents() == {
        "claude-code", "hermes", "codex", "gemini-cli", "copilot-cli", "aider",
    }
    assert "opencode" not in runnable_agents()


@pytest.mark.parametrize("agent, expected", [
    ("hermes", ["-z", "do X"]),
    ("codex", ["exec", "--dangerously-bypass-approvals-and-sandbox", "do X"]),
    ("gemini-cli", ["-p", "do X", "--approval-mode", "yolo"]),
    ("copilot-cli", ["-p", "do X", "--allow-all-tools"]),
    ("aider", ["--message", "do X", "--yes-always"]),
])
def test_build_argv_per_stdout_agent(agent, expected):
    assert RUNNERS[agent].build_argv("do X") == expected


def test_claude_is_stream_json_and_not_stdout_built():
    spec = RUNNERS["claude-code"]
    assert spec.mode == "stream-json"
    assert spec.build_argv is None  # claude argv is built in worker.run_claude


def test_run_stdout_success(tmp_path):
    spec = RunnerSpec(binary="printf", mode="stdout", build_argv=lambda p: [p])
    res = run_stdout(spec, "hello", str(tmp_path))
    assert res.text == "hello"
    assert res.is_error is False
    assert res.session_id is None


def test_run_stdout_nonzero_exit_is_error(tmp_path):
    spec = RunnerSpec(
        binary="sh", mode="stdout",
        build_argv=lambda p: ["-c", "echo oops >&2; exit 1"],
    )
    res = run_stdout(spec, "ignored", str(tmp_path))
    assert res.is_error is True
    assert "oops" in res.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_runners.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'daemon.runners'`.

- [ ] **Step 3: Write the implementation**

Create `daemon/runners.py`:

```python
"""Agent runner registry — how the loom worker invokes each coding-agent CLI.

The worker is otherwise agent-agnostic (worktree, progress, commit, status are
generic). The only agent-specific knowledge is *how to invoke the CLI headlessly*
and *how to read its result*. That lives here as a declarative registry, so
adding an agent is a few lines of data rather than new control flow.

Output modes:
  - "stream-json": Claude only. Built and parsed in daemon.worker.run_claude
    (live progress, session_id, budget). build_argv is None here.
  - "stdout":      everyone else. Run the command, capture stdout as the result
    text; a non-zero exit code is an error. Handled by run_stdout().
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class AgentResult:
    """Neutral result returned by every runner. session_id is Claude-only."""
    text: str
    session_id: Optional[str]
    is_error: bool


@dataclass
class RunnerSpec:
    """Declarative description of how to run one agent CLI headlessly."""
    binary: str
    mode: str  # "stream-json" | "stdout"
    build_argv: Optional[Callable[[str], list[str]]] = None  # (prompt) -> argv after binary
    streams_progress: bool = False
    supports_resume: bool = False
    supports_budget: bool = False


# Canonical agent name -> RunnerSpec. Keys MUST match daemon.known_agents names
# and the suffix-stripped assignee in daemon.api._route_task_execution.
RUNNERS: dict[str, RunnerSpec] = {
    "claude-code": RunnerSpec(
        binary="claude", mode="stream-json", build_argv=None,
        streams_progress=True, supports_resume=True, supports_budget=True,
    ),
    "hermes": RunnerSpec(
        binary="hermes", mode="stdout",
        build_argv=lambda prompt: ["-z", prompt],
    ),
    "codex": RunnerSpec(
        binary="codex", mode="stdout",
        build_argv=lambda prompt: [
            "exec", "--dangerously-bypass-approvals-and-sandbox", prompt,
        ],
    ),
    "gemini-cli": RunnerSpec(
        binary="gemini", mode="stdout",
        build_argv=lambda prompt: ["-p", prompt, "--approval-mode", "yolo"],
    ),
    "copilot-cli": RunnerSpec(
        binary="copilot", mode="stdout",
        build_argv=lambda prompt: ["-p", prompt, "--allow-all-tools"],
    ),
    "aider": RunnerSpec(
        binary="aider", mode="stdout",
        build_argv=lambda prompt: ["--message", prompt, "--yes-always"],
    ),
}


def runnable_agents() -> set[str]:
    """Canonical names of agents the daemon can spawn a worker for."""
    return set(RUNNERS)


def run_stdout(
    spec: RunnerSpec,
    prompt: str,
    cwd: str,
    on_progress: Optional[Callable[[str], None]] = None,
) -> AgentResult:
    """Run a plain-stdout agent CLI to completion in ``cwd``.

    Captures stdout as the result text; a non-zero exit marks an error (falling
    back to stderr for the message when stdout is empty).
    """
    if spec.build_argv is None:
        raise ValueError(f"{spec.binary}: stdout runner requires build_argv")
    argv = [spec.binary, *spec.build_argv(prompt)]
    if on_progress:
        on_progress(f"Running {spec.binary}…")
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    text = (proc.stdout or "").strip()
    if proc.returncode != 0:
        msg = text or (proc.stderr or "").strip() or f"{spec.binary} exited non-zero"
        return AgentResult(text=msg, session_id=None, is_error=True)
    return AgentResult(text=text, session_id=None, is_error=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_runners.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add daemon/runners.py tests/test_runners.py
git commit -m "feat: add agent runner registry and generic stdout runner"
```

---

### Task 2: Worker dispatch via `run_agent`

**Files:**
- Modify: `daemon/worker.py` (imports + `ClaudeResult` alias at lines 17-30; `process_task` call at lines 198-204; add `run_agent`)
- Test: `tests/test_worker.py` (additions)

**Interfaces:**
- Consumes: `AgentResult`, `RUNNERS`, `run_stdout` from `daemon.runners` (Task 1).
- Produces: `run_agent(agent: str, prompt: str, cwd: str, model=None, max_budget_usd=5.0, resume=None, on_progress=None) -> AgentResult` in `daemon.worker`; `ClaudeResult` remains importable (alias of `AgentResult`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_worker.py`:

```python
from daemon.runners import AgentResult


def test_run_agent_routes_claude_to_run_claude(monkeypatch):
    monkeypatch.setattr(worker_mod, "run_claude",
                        lambda *a, **k: AgentResult("c", "s", False))
    r = worker_mod.run_agent("claude-code", "p", "/tmp")
    assert r.text == "c" and r.session_id == "s"


def test_run_agent_unknown_raises():
    with pytest.raises(ValueError):
        worker_mod.run_agent("nonesuch", "p", "/tmp")


def test_process_task_uses_run_stdout_for_non_claude(monkeypatch):
    w = _CaptureWorker(project="noor", agent="hermes",
                       project_path="/tmp/noor", base_url="http://x")
    monkeypatch.setattr(worker_mod, "current_branch", lambda repo: "main")
    monkeypatch.setattr(worker_mod, "create_worktree", lambda *a, **k: None)
    monkeypatch.setattr(worker_mod, "commit_all", lambda *a, **k: True)
    captured = {}

    def fake_run_stdout(spec, prompt, cwd, on_progress=None):
        captured["binary"] = spec.binary
        return AgentResult("hermes did it", None, False)

    monkeypatch.setattr(worker_mod, "run_stdout", fake_run_stdout)
    w.process_task({"id": "h1", "title": "T", "instruction": "x",
                    "acceptance_criteria": "", "result": None})

    assert captured["binary"] == "hermes"
    assert w.patches[-1][1]["status"] == "done"
    body = __import__("json").loads(w.patches[-1][1]["result"])
    assert body["summary"] == "hermes did it"
```

Add `import pytest` to the top of `tests/test_worker.py` if not present (it currently is not).

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_worker.py -v -k "run_agent or non_claude"`
Expected: FAIL — `run_agent` does not exist / `worker_mod` has no attribute `run_stdout`.

- [ ] **Step 3: Edit the imports and `ClaudeResult`**

In `daemon/worker.py`, replace the dataclass import and `ClaudeResult` class. Change lines 17-30 from:

```python
from dataclasses import dataclass
from datetime import datetime, timezone

from daemon.worktree import create_worktree, commit_all, current_branch

logger = logging.getLogger("loom.worker")


@dataclass
class ClaudeResult:
    text: str
    session_id: str | None
    is_error: bool
```

to:

```python
from datetime import datetime, timezone

from daemon.worktree import create_worktree, commit_all, current_branch
from daemon.runners import AgentResult, RUNNERS, run_stdout

logger = logging.getLogger("loom.worker")

# Back-compat alias: run_claude still returns this; tests import ClaudeResult.
ClaudeResult = AgentResult
```

(Keep `run_claude` exactly as-is; it returns `ClaudeResult(...)` which is now `AgentResult`.)

- [ ] **Step 4: Add `run_agent` after `run_claude`**

In `daemon/worker.py`, immediately after the `run_claude` function (after its `return ClaudeResult(...)` line, before `class Worker`), add:

```python
def run_agent(agent, prompt, cwd, model=None, max_budget_usd=5.0,
              resume=None, on_progress=None) -> AgentResult:
    """Dispatch to the right runner for ``agent`` (a canonical name).

    Claude keeps its rich stream-json path (run_claude); every other registered
    agent runs through the generic stdout runner. Unknown agents raise — the API
    spawn gate (daemon.api.LOOM_WORKER_AGENTS) only routes registered agents here.
    """
    if agent == "claude-code":
        return run_claude(prompt, cwd, model=model,
                          max_budget_usd=max_budget_usd, resume=resume,
                          on_progress=on_progress)
    spec = RUNNERS.get(agent)
    if spec is None:
        raise ValueError(f"no runner for agent {agent!r}")
    return run_stdout(spec, prompt, cwd, on_progress=on_progress)
```

- [ ] **Step 5: Route `process_task` through `run_agent`**

In `daemon/worker.py`, replace the `run_claude(...)` call in `process_task` (currently lines 199-204):

```python
        result = run_claude(
            prompt, cwd=workspace, model=self.model, max_budget_usd=self.max_budget_usd,
            resume=resume,
            on_progress=lambda line: self._post_progress(
                task_id, line, kind="tool" if line.startswith("tool:") else "text"),
        )
```

with:

```python
        result = run_agent(
            self.agent, prompt, cwd=workspace, model=self.model,
            max_budget_usd=self.max_budget_usd, resume=resume,
            on_progress=lambda line: self._post_progress(
                task_id, line, kind="tool" if line.startswith("tool:") else "text"),
        )
```

- [ ] **Step 6: Run the full worker suite to verify pass + no regressions**

Run: `pytest tests/test_worker.py -v`
Expected: PASS — the three new tests plus all pre-existing tests (the claude path still flows through the patched `run_claude`).

- [ ] **Step 7: Commit**

```bash
git add daemon/worker.py tests/test_worker.py
git commit -m "feat: dispatch worker execution per-agent via run_agent"
```

---

### Task 3: API spawn gate + runnable endpoint

**Files:**
- Modify: `daemon/api.py` (import near line 21; `LOOM_WORKER_AGENTS` at line 46; new endpoint after `list_known_agents`, ~line 297)
- Test: `tests/test_api.py` (additions)

**Interfaces:**
- Consumes: `daemon.runners.runnable_agents` (Task 1).
- Produces: `GET /api/agents/runnable -> {"agents": [str, ...]}` (sorted); `LOOM_WORKER_AGENTS` now equals `runnable_agents()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api.py`:

```python
def test_runnable_agents_endpoint(client):
    r = client.get("/api/agents/runnable")
    assert r.status_code == 200
    agents = r.json()["agents"]
    assert "claude-code" in agents
    assert "hermes" in agents
    assert "opencode" not in agents


async def test_running_transition_spawns_worker_for_runnable_agent(client):
    fake = _FakeSupervisor()
    api_module.supervisor = fake

    r = client.post("/api/projects/noor/tasks", json={
        "project": "noor", "title": "T", "instruction": "do x",
        "assignee": "hermes-noor",
    })
    assert r.status_code == 201
    tid = r.json()["id"]

    r = client.patch(f"/api/projects/noor/tasks/{tid}", json={"status": "running"})
    assert r.status_code == 200

    # hermes is now a runnable agent → the supervisor was asked to spawn it,
    # rather than the task being dropped into the inbox.
    assert any(agent == "hermes" for (_proj, agent, _path, _tid) in fake.spawned)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api.py -v -k "runnable or spawns_worker"`
Expected: FAIL — 404 on `/api/agents/runnable`; and the spawn test fails because `hermes` is not yet in `LOOM_WORKER_AGENTS` (no spawn recorded).

- [ ] **Step 3: Derive `LOOM_WORKER_AGENTS` from the registry**

In `daemon/api.py`, add the import to the daemon import block (after line 21's models import is fine):

```python
from daemon import runners
```

Then replace line 46:

```python
LOOM_WORKER_AGENTS = {"claude-code"}        # agent names the loom worker runs via claude -p
```

with:

```python
LOOM_WORKER_AGENTS = runners.runnable_agents()   # registry-derived: agents the worker can spawn
```

- [ ] **Step 4: Add the runnable endpoint**

In `daemon/api.py`, after the `list_known_agents` handler (ends at line 296), add:

```python
@app.get("/api/agents/runnable")
async def list_runnable_agents():
    """Canonical names of agents the daemon can run as a worker (registry-derived)."""
    return {"agents": sorted(runners.runnable_agents())}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_api.py -v -k "runnable or spawns_worker"`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full daemon suite (no regressions)**

Run: `pytest tests/ -v`
Expected: PASS across the suite.

- [ ] **Step 7: Commit**

```bash
git add daemon/api.py tests/test_api.py
git commit -m "feat: derive worker spawn gate from registry; add runnable-agents endpoint"
```

---

### Task 4: Dashboard API client + i18n strings

**Files:**
- Modify: `dashboard/lib/api.ts` (add after `listKnownAgents`, ~line 204)
- Modify: `dashboard/messages/en.json` (`TaskDetail` block)
- Modify: `dashboard/messages/ar.json` (`TaskDetail` block)

**Interfaces:**
- Produces: `listRunnableAgents(): Promise<{ agents: string[] }>`; i18n keys `TaskDetail.externalAgentTitle`, `TaskDetail.externalAgentBody` (the latter takes an `{agent}` placeholder).

- [ ] **Step 1: Add the API client function**

In `dashboard/lib/api.ts`, after the `listKnownAgents` function (around line 204), add:

```typescript
export async function listRunnableAgents(): Promise<{ agents: string[] }> {
  return fetchApi("/api/agents/runnable");
}
```

- [ ] **Step 2: Add the English strings**

In `dashboard/messages/en.json`, inside the `TaskDetail` object, add after `"noWorkerBody"` (add a comma to the existing last entry):

```json
    "externalAgentTitle": "External agent — can't run from here",
    "externalAgentBody": "{agent} runs in its own process and can't be started from the dashboard. Assign a runnable agent (e.g. claude-code) to run this task here."
```

- [ ] **Step 3: Add the Arabic strings**

In `dashboard/messages/ar.json`, inside the `TaskDetail` object, add after `"noWorkerBody"` (add a comma to the existing last entry):

```json
    "externalAgentTitle": "وكيل خارجي — لا يمكن تشغيله من هنا",
    "externalAgentBody": "{agent} يعمل في عمليته الخاصة ولا يمكن بدؤه من لوحة التحكم. عيّن وكيلًا قابلًا للتشغيل (مثل claude-code) لتشغيل هذه المهمة هنا."
```

- [ ] **Step 4: Verify lint + build**

Run (from `dashboard/`): `npm run lint && npm run build`
Expected: lint clean; build succeeds (JSON valid, no type errors).

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/api.ts dashboard/messages/en.json dashboard/messages/ar.json
git commit -m "feat: add runnable-agents client and external-agent i18n strings"
```

---

### Task 5: Gate the Run button on runnable agents

**Files:**
- Modify: `dashboard/app/[locale]/projects/[id]/tasks/page.tsx`
- Modify: `dashboard/components/task-detail-drawer.tsx`

**Interfaces:**
- Consumes: `listRunnableAgents` and the new i18n keys (Task 4).
- Produces: `TaskDetailDrawer` gains a required `assigneeRunnable: boolean` prop.

- [ ] **Step 1: Fetch the runnable set in the tasks page**

In `dashboard/app/[locale]/projects/[id]/tasks/page.tsx`:

1. Extend the import (line 8-11) to include `listRunnableAgents`:

```typescript
import {
  listAgentTasks, getProject, updateAgentTask, listWorkers, listRunnableAgents,
  type AgentTask, type AgentTaskStatus, type AgentInfo,
} from "@/lib/api";
```

2. Add state after `workerIds` (line 26):

```typescript
  const [runnable, setRunnable] = useState<Set<string>>(new Set());
```

3. In `loadData`, add the fetch to the `Promise.all` and store it (replace lines 31-38):

```typescript
      const [taskList, project, workers, runnableRes] = await Promise.all([
        listAgentTasks(id),
        getProject(id),
        listWorkers(id),
        listRunnableAgents(),
      ]);
      setTasks(taskList);
      setAgents(project.agents || []);
      setWorkerIds(new Set(workers.running));
      setRunnable(new Set(runnableRes.agents));
```

- [ ] **Step 2: Derive `assigneeRunnable` and pass it to the drawer**

In the same file, just before the `return (` (after line 95), add the derivation (mirrors the daemon's `assignee.removesuffix(f"-{project_id}")`):

```typescript
  const assigneeName = selected?.assignee
    ? selected.assignee.endsWith(`-${id}`)
      ? selected.assignee.slice(0, -(id.length + 1))
      : selected.assignee
    : null;
  const assigneeRunnable = assigneeName ? runnable.has(assigneeName) : false;
```

Then add the prop to `<TaskDetailDrawer>` (after the `workerRunning=` line, line 128):

```typescript
        assigneeRunnable={assigneeRunnable}
```

- [ ] **Step 3: Accept and use the prop in the drawer**

In `dashboard/components/task-detail-drawer.tsx`:

1. Add to `TaskDetailDrawerProps` (after `workerRunning: boolean;`, line 29):

```typescript
  assigneeRunnable: boolean;
```

2. Destructure it in the component signature (after `workerRunning,`, line 56):

```typescript
  assigneeRunnable,
```

3. Replace the derived flags (lines 173-176):

```typescript
  const isDone = task.status === "done";
  const isBlocked = task.status === "blocked";
  const showNoWorker = task.status === "running" && !workerRunning;
  const canRun = !workerRunning && !isDone && !!task.assignee;
```

with:

```typescript
  const isDone = task.status === "done";
  const isBlocked = task.status === "blocked";
  const assigneeShort = task.assignee
    ? agents.find((a) => a.agent_id === task.assignee)?.agent_name ?? task.assignee
    : "";
  const isExternal = !!task.assignee && !assigneeRunnable;
  const showNoWorker = task.status === "running" && !workerRunning && !isExternal;
  const showExternal = task.status === "running" && !workerRunning && isExternal;
  const canRun = !workerRunning && !isDone && !!task.assignee && assigneeRunnable;
```

4. Add the external-agent note next to the existing `showNoWorker` block (after the `showNoWorker` block, after line 217):

```tsx
        {showExternal && (
          <div className="rounded-md border border-zinc-700 bg-zinc-800/40 p-2">
            <p className="text-zinc-300 font-medium">{t("externalAgentTitle")}</p>
            <p className="text-zinc-400 mt-1">{t("externalAgentBody", { agent: assigneeShort })}</p>
          </div>
        )}
```

(The Run button already disables on `!canRun`, so external agents get a disabled Run plus this explanation. No further button change needed.)

- [ ] **Step 4: Verify lint + build**

Run (from `dashboard/`): `npm run lint && npm run build`
Expected: lint clean; build succeeds (drawer now requires `assigneeRunnable`, supplied by the page).

- [ ] **Step 5: Manual verification**

With the daemon running (`loom --port 8472`) and `npm run dev`:
1. Open a project's Tasks tab; select a task assigned to `hermes`.
2. Confirm the drawer shows the "External agent" note **only if** hermes is not runnable; since hermes IS in the registry, the note should NOT show and **Run is enabled**.
3. Select/assign a task to `opencode` (registered, no runner) → the external-agent note shows and Run is disabled.
4. Click **Run** on the hermes task → confirm a worker spawns (badge flips to "Worker running", activity shows worktree + agent progress) instead of another "Dispatched via inbox" line.

- [ ] **Step 6: Commit**

```bash
git add dashboard/app/[locale]/projects/[id]/tasks/page.tsx dashboard/components/task-detail-drawer.tsx
git commit -m "feat: gate Run button on runnable agents; show external-agent note"
```

---

## Self-Review

**1. Spec coverage:**
- `daemon/runners.py` registry + `run_agent` dispatcher → Tasks 1-2. ✓
- Verified command table (hermes/codex/gemini/copilot/aider) → Task 1 `RUNNERS` + parametrized test. ✓
- Claude delegation / `run_claude` + `ClaudeResult` preserved → Task 2 (alias + claude branch) + green `test_worker.py`. ✓
- `LOOM_WORKER_AGENTS` derived from registry → Task 3. ✓
- `GET /api/agents/runnable` → Task 3. ✓
- UI gating (page derive + drawer note) → Tasks 4-5. ✓
- i18n in both locales → Task 4. ✓
- No new budget/timeout cap → honored (none added). ✓
- Testing strategy (test_runners, test_api, test_worker green) → Tasks 1-3. ✓

**2. Placeholder scan:** No TBD/TODO; every code/edit step shows full code and exact run commands with expected output. ✓

**3. Type consistency:** `AgentResult(text, session_id, is_error)` field order is used identically in `run_stdout`, the worker tests, and the `ClaudeResult` alias. `run_agent` signature in Task 2 matches the `process_task` call site. `assigneeRunnable: boolean` defined in the drawer (Task 5 step 3) matches the prop passed by the page (Task 5 step 2) and the client return type `{ agents: string[] }` (Task 4). Registry keys are consistent (`gemini-cli`, `copilot-cli`) across runners, the gate, and tests. ✓

## Notes / accepted risks

- Non-Claude agents run with auto-approve flags and **no USD/timeout cap** inside the per-task git worktree (spec decision). Worktree branch isolation + reviewable diff is the only containment.
- Progress for stdout agents is coarse (`Running <binary>…` then final summary); live per-tool progress is future work.
- `opencode`/`cursor` have no runner → they remain external and now get an honest disabled-Run note instead of a silent no-op.
