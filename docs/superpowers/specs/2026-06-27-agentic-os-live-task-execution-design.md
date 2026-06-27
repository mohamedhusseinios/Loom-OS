# Loom — Live Task-Execution View & Dashboard-Launched Workers — Design Spec

**Date:** 2026-06-27
**Status:** Design phase (approved in brainstorming)
**Project:** Loom OS (`agentic-os` repo) — daemon + Next.js dashboard

## Overview

When a Kanban card is dragged to **Running**, nothing visibly happens and the user
cannot tell whether an agent is working. This is not (only) a UI gap — it is a
**declared-state vs. actual-state** gap:

- Moving a card to Running only flips a database row (`PATCH /tasks/{id}`). It does
  **not** spawn anything.
- The `loom worker` process that actually executes Running tasks is a **separate,
  manually-started, long-running poll loop**. If it is not running, the card sits in
  Running forever.
- An agent showing `online` (a recent heartbeat) is **not** the same as a `loom worker`
  polling the Kanban — this false signal is what misled the user.
- Even with a worker running, the worker posts progress lines to
  `POST /tasks/{id}/progress`, but the daemon only **relays them over WebSocket and never
  persists them** (`daemon/api.py:660`), and `task-detail-drawer.tsx` does not subscribe.
  So: nothing live, nothing on reload.

This feature makes a task **run when moved to Running**, shows a **live read-only
transcript** of what the agent does (chat-styled, persisted), and **surfaces worker
liveness** so the user always knows whether something is executing.

## Design Decisions (from brainstorming)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope | Observe + worker liveness + launch/stop worker from the dashboard | The real failure was "no worker attached + no visibility"; a progress view alone would show an empty screen |
| Worker lifecycle | **One-shot per task** — spawn a worker that does exactly one task, then exits; tracked by task id | Matches the "move card → it runs" mental model; makes liveness crisp ("this task has a live process or it doesn't") |
| Interactivity | **Read-only, persisted transcript** | `claude -p` runs headless/non-interactive; two-way steering is a much larger, separate effort |
| Spawn trigger | **Auto-spawn on drag-to-Running**, with an explicit Run button as manual fallback | Reuses the existing optimistic-update board path; Run re-triggers the same path |
| Stop semantics | Kill the subprocess, mark task `blocked` ("cancelled by user"), keep the worktree | Preserves partial work for inspection |
| Feed granularity (v1) | One line per tool call / text snippet (existing `_summarize_event`) + lifecycle milestones | Richer detail (full tool inputs, token stream) is a later enhancement |

## Goals / Non-Goals

**Goals**
- Drag-to-Running (or a Run button) launches a one-shot worker via the daemon, with no
  terminal and no manually-typed project path.
- A task detail "chat window" shows a persisted, replayable transcript of the agent's
  work plus lifecycle milestones, updating live.
- The UI always shows whether a live worker is attached to a Running task; the
  exact-confusion case ("Running but nothing executing") is called out explicitly with a
  one-click Run.

**Non-Goals (v1)**
- Two-way / steerable chat (typing to the agent mid-task).
- A global concurrency or cost cap across simultaneously-running tasks (per-task
  `--max-budget-usd` remains).
- PID persistence across daemon restarts (orphaned Running tasks recover via Run +
  session resume).
- Streaming raw token output or full tool-call inputs into the transcript.

## Confirmed Integration Points (existing code)

- `daemon/api.py:634` `update_agent_task` (PATCH) → `registry.update_agent_task` → emits
  `task:updated`. **Spawn hook goes here.**
- `daemon/api.py:660` `task_progress` (POST) → emits `task:progress` only (ephemeral).
  **Persistence + history added here.**
- `daemon/worker.py:160` `Worker.process_task` already performs the full one-shot flow
  (worktree, `run_claude`, progress posts, finding, status update). It already supports
  `--resume` via a stored `session_id` (worker.py:189-194).
- `daemon/registry.py:49` `projects.project_path` is stored — the daemon already knows
  each project's local path, so it can launch a worker with `--project-path`
  automatically.
- `dashboard/lib/use-websocket.tsx:66` `subscribe(key, fn)` — components subscribe by
  event type (`"task:progress"`) or by `"project:<id>"`.
- `dashboard/app/[locale]/projects/[id]/tasks/page.tsx:61` `handleMove` already calls
  `updateAgentTask(id, taskId, { status })` — so drag-to-Running already hits the PATCH
  endpoint we are hooking.
- `dashboard/components/task-detail-drawer.tsx` is the existing drawer shell that becomes
  the chat window.
- Daemon already spawns subprocesses for graphify (`graph_engine.py`), establishing the
  subprocess pattern to follow.

## Architecture & Data Flow

```
  Dashboard (drag card → Running, or click Run)
        │  PATCH /tasks/{id} {status:running}
        ▼
  api.py update_agent_task ──► registry (status=running) ──► emit task:updated
        │
        │  NEW: if status→running & assignee set & not supervisor.is_running(id)
        ▼
  WorkerSupervisor.spawn(task_id)                         ← NEW daemon/supervisor.py
        │  Popen: sys.executable -m daemon.main worker --once --task <id>
        │         --project <p> --agent <a> --project-path <path> --max-budget-usd <n>
        ▼
  worker.py process_task()  (+ --once entrypoint, + milestone posts)
        │  POST /tasks/{id}/progress {kind, message}
        ▼
  api.py task_progress ──► INSERT task_progress row        ← NEW (persist)
        │              └──► emit task:progress {id, seq, kind, message}
        ▼                                         │ WebSocket
  worker PATCHes task → done/blocked              ▼
        │  emit task:updated                Drawer "chat window" (live append)
        ▼  supervisor.reap() → emit worker:exited
  Drawer on open: GET /tasks/{id}/progress (history) + GET /projects/{id}/workers
```

**Key transformation:** progress flips from *fire-and-forget* to a *durable transcript*.
`POST /progress` keeps emitting the WS event (live feed) **and** writes a row, so the
drawer can replay full history on reload or late open.

## Backend Changes (daemon)

### 1. `daemon/supervisor.py` (new)

`WorkerSupervisor` holding `{task_id: subprocess.Popen}`:

- `spawn(project, agent, project_path, task_id, max_budget_usd)` → builds
  `[sys.executable, "-m", "daemon.main", "worker", "--once", "--task", task_id,
  "--project", project, "--agent", agent, "--project-path", project_path,
  "--max-budget-usd", str(...)]`, `Popen`, stores the handle. Using `sys.executable -m`
  (not the `loom` PATH entry) guarantees the child runs in the daemon's interpreter/venv.
- `is_running(task_id) -> bool` (polls the stored handle; a finished proc is treated as
  not running).
- `running_ids() -> list[str]`.
- `stop(task_id)` → `terminate()` (then `kill()` after a short grace), discard handle.
- `reap()` → poll handles; for any that exited, drop them and emit `worker:exited`.

Registered as a module-global in `api.py` (like `registry`, `router`, `graph_engine`).
A lightweight reaper runs from the existing broadcast/lifespan loop (or a small periodic
task); in **test mode** (`registry is not None` sentinel) the reaper is skipped, matching
the existing pattern.

The `agent` value is derived from `assignee` by stripping the `-{project}` suffix
(assignee format is `{agent}-{project}`, see `worker.py:113`).

### 2. Spawn hook — `update_agent_task` (api.py:634)

After the status update and `task:updated` emit, add:

```
if payload.status == AgentTaskStatus.RUNNING and updated.assignee \
        and not supervisor.is_running(task_id):
    project = await registry.get_project(project_id)
    agent = updated.assignee.removesuffix(f"-{project_id}")
    supervisor.spawn(project_id, agent, project.project_path, task_id, MAX_BUDGET)
    await router._emit_event("worker:started", project_id, {"id": task_id})
```

- **Idempotent**: the `is_running` guard prevents double-spawn (mirrors the existing
  dispatch dual-write idempotency contract).
- **No assignee → no spawn** (UI shows "assign an agent to run").
- Guarded for test mode (`supervisor is not None`).

### 3. Persist progress — `task_progress` table + endpoints

New table:

```sql
CREATE TABLE IF NOT EXISTS task_progress (
    task_id TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    kind    TEXT NOT NULL,          -- milestone | tool | text | error | summary
    message TEXT NOT NULL,
    ts      TEXT NOT NULL,
    PRIMARY KEY (task_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_task_progress_task ON task_progress(task_id);
```

- `registry.append_progress(task_id, kind, message) -> int` — computes next `seq`
  (`MAX(seq)+1` per task), inserts, returns `seq`.
- `registry.list_progress(task_id) -> list[TaskProgressRecord]` — ordered by `seq`.
- `POST /tasks/{id}/progress` (api.py:660) now: `seq = await registry.append_progress(...)`
  then emit `task:progress` with `{id, seq, kind, message}`.
- `GET /tasks/{id}/progress` (new) → ordered transcript for initial load.

`TaskProgressPayload` gains an optional `kind: str = "text"`. Worker posts a `kind` where
useful; default `text` keeps backward compatibility.

### 4. Worker one-shot mode — `main.py` + `worker.py`

- `main.py` `worker` subcommand gains `--once` and `--task <id>`. In one-shot mode the
  worker: builds a `Worker`, fetches its task by filtering the existing
  `GET /tasks?status=running` for the matching id (reusing `Worker._get_running_tasks`,
  worker.py:135 — no new by-id route needed), calls `process_task(task)`, and exits (no
  poll loop, no heartbeat loop). It still `ensure_registered()` first. If the id is not
  found in Running (e.g. it was moved away before the worker started), it exits cleanly.
- `process_task` gains milestone posts via `_post_progress(task_id, line, kind="milestone")`
  at: worktree created, agent started, done, blocked. `_post_progress` gains a `kind`
  parameter (default `text`); stream lines post as `kind="tool"`/`"text"` based on the
  event; the final summary posts as `kind="summary"`, errors as `kind="error"`.
- Re-running a stuck task reuses the existing `--resume` path (stored `session_id`), so a
  worker that died / a daemon that restarted can **continue** the Claude session rather
  than restart from scratch.

### 5. Worker control + status endpoints

- `POST /tasks/{id}/worker/start` → spawn (same guard as the auto hook); used by the Run
  button and to re-run orphaned tasks.
- `POST /tasks/{id}/worker/stop` → `supervisor.stop(id)`, PATCH task to `blocked` with
  `result` note `{"cancelled": true, ...}`, emit `task:updated` + `worker:exited`.
- `GET /projects/{id}/workers` → `{ "running": [task_id, ...] }` for the board/drawer to
  seed liveness on load.
- New WS events: `worker:started`, `worker:exited` (payload `{id}`).

## Frontend Changes (dashboard)

`dashboard/components/task-detail-drawer.tsx` becomes the chat window (its shell already
has status/assignee/instruction/criteria/result/diff+merge):

- **Worker-status pill** (header): `● running` / `○ no worker — [Run]` / `done` /
  `blocked`, derived from a `runningWorkerIds` set.
- **Run / Stop button**: Run when the task is idle and has an assignee; Stop when a worker
  is live. Calls `startWorker` / `stopWorker`.
- **Transcript feed**: chat-styled scrolling bubbles rendering `{kind, message}` items
  (milestone, tool, text, error, summary), auto-scroll to bottom. Seeded from
  `GET /tasks/{id}/progress` on open, then appended live via `subscribe("task:progress", …)`
  filtered by `data.id === task.id`, de-duplicated by `seq`.
- **Exact-confusion banner**: when `status === "running"` and the task is **not** in
  `runningWorkerIds`, show an amber banner — "Queued, but no worker is executing this" —
  with a **Run** button and, as fallback, the exact terminal command
  (`loom worker --once --task … --project … --agent … --project-path …`).
- Keep instruction / acceptance criteria / result summary / diff + merge as-is.

`dashboard/app/[locale]/projects/[id]/tasks/page.tsx`:
- Track `runningWorkerIds` (a `Set<string>`), seeded by `listWorkers(id)` and kept current
  via `worker:started` / `worker:exited` subscriptions (under the existing `project:${id}`
  handler). Pass down to the drawer (and optionally to the board for a per-card "live" dot).

`dashboard/lib/api.ts`:
- `getTaskProgress(projectId, taskId)`, `startWorker(projectId, taskId)`,
  `stopWorker(projectId, taskId)`, `listWorkers(projectId)`.
- Types: `TaskProgressItem { seq; kind; message; ts }`, `WorkersResponse { running: string[] }`.
- WS event types: extend with `task:progress` (now `{id, seq, kind, message}`),
  `worker:started`, `worker:exited`.

**i18n:** add all new strings (pill states, Run/Stop, banner copy, transcript empty state)
to **both** `messages/en.json` and `messages/ar.json` (RTL).

## Error Handling & Edge Cases

- **Stop** kills the subprocess, marks the task `blocked` ("cancelled by user"), leaves
  the worktree for inspection, emits `worker:exited`.
- **Daemon restart** clears the supervisor map; tasks still `running` show "no worker
  attached" (honest stale state). **Run** re-spawns and resumes via `session_id`.
- **Concurrency/cost:** one-shot-per-task means N running tasks = N `claude` processes =
  N × budget. Per-task `--max-budget-usd` stays; a global cap is out of scope (v1).
- **Worktree/git failure** already routes the task to `blocked` with the error
  (`worker.py:173-179`), which the transcript now surfaces as a `kind="error"` line.
- **Missing `claude` CLI / bad project_path**: the child exits non-zero; `run_claude`
  marks `is_error`, the task goes `blocked` with the stderr text, and `worker:exited`
  fires — so the UI never shows a phantom "running".
- **Spawn for an unregistered/path-less project**: `get_project` returns the path; if
  absent, the start endpoint returns 400 and the banner explains.

## Testing Strategy

Follows the established module-global test pattern (assign `api_module.registry`,
`api_module.supervisor`, etc. before constructing `TestClient`; `lifespan` test-mode
sentinel skips the watcher/broadcast/reaper).

- **Worker one-shot** (`tests/test_worker.py`): `--once --task` processes exactly one task
  and exits; milestone posts emitted in order; resume path used when `session_id` present.
- **Supervisor** (new `tests/test_supervisor.py`): `spawn` stores a handle (mock `Popen`);
  `is_running` reflects process state; `stop` terminates; `reap` drops exited procs and
  emits `worker:exited`.
- **Progress persistence** (`tests/test_api.py`): `POST /progress` inserts and returns
  `seq`; `GET /progress` returns items ordered by `seq`; WS event carries `seq` + `kind`.
- **Spawn hook** (`tests/test_api.py`): PATCH→running with assignee calls
  `supervisor.spawn` once; second PATCH while running does **not** re-spawn (idempotent);
  PATCH→running without assignee does **not** spawn; `worker/stop` blocks the task and
  emits `worker:exited`.

## Out of Scope / Future Enhancements

- Two-way steerable chat (interactive Claude session with stdin).
- Global concurrency/cost ceiling and a worker queue.
- Richer transcript detail: full tool inputs, per-step file diffs, token/cost meter.
- PID persistence + reattach across daemon restarts.
- Per-card live indicator and a project-wide "workers" panel.

## Files Touched (summary)

**Daemon:** `daemon/supervisor.py` (new), `daemon/api.py` (spawn hook, progress persist,
worker control/status endpoints, module-global + reaper), `daemon/registry.py`
(`task_progress` table + `append_progress`/`list_progress`), `daemon/worker.py`
(`--once` path, milestone posts, `_post_progress` kind), `daemon/main.py` (`--once`/`--task`
flags), `daemon/models.py` (`TaskProgressPayload.kind`, `TaskProgressRecord`,
worker-status models, new WS event names).

**Dashboard:** `components/task-detail-drawer.tsx` (chat window), `app/[locale]/projects/[id]/tasks/page.tsx`
(worker-id tracking), `lib/api.ts` (new calls + types), `lib/use-websocket.tsx` (new event
types if typed centrally), `messages/en.json` + `messages/ar.json` (new strings).

**Tests:** `tests/test_worker.py`, `tests/test_supervisor.py` (new), `tests/test_api.py`.

---

# Addendum (2026-06-27): Unify dispatch ↔ Kanban (route-by-assignee)

**Why:** The repo has two parallel task systems — the legacy **dispatch** path (the
`tasks` table, `POST /dispatch` + `GET /dispatches`, used by `dispatch-modal` /
`dispatch-history` / `agent-wiring` on the Agents page) and the **Kanban** path (the
`agent_tasks` table, the Tasks board, and everything Part 1 builds). They have separate
storage, separate status vocabularies, and separate lifecycles. This addendum folds
dispatch into the Kanban system so there is **one** task store, board, lifecycle, and
detail/chat view.

## Decisions (confirmed in brainstorming)

| Decision | Choice |
|----------|--------|
| Storage | Dispatch creates an `agent_tasks` row. The legacy `tasks` table is **deprecated in place** — left intact, no destructive migration; the unified UI no longer reads it. |
| Dispatch timing | Dispatch lands the task in **Ready** (not auto-run). Nothing executes until the task enters Running. No surprise `claude` spend. |
| Execution routing | On entering **Running**, route by assignee: first-party agents (name ∈ `LOOM_WORKER_AGENTS`, default `{"claude-code"}`) run via the loom worker (Part 1); all other (external) agents get an inbox `task-<id>.json` dropped for filesystem-protocol pickup. |
| Identity mapping | Dispatch `target_agent` is an agent **name** (e.g. `hermes`); the unified task's `assignee` is the agent **id** `{name}-{project}`. |
| Inbox unification | The watcher's `_handle_task` upserts an `agent_tasks` row idempotently (by id), so any `task-*.json` dropped on the inbox also appears on the board. |

## Flow

```
Agents page → Dispatch modal → POST /dispatch
   → registry.create_agent_task(task_id, assignee={name}-{project}, status=ready,
                                title=first line of instruction, priority=map(low/med/high))
   → emit task:created                              (card appears on the board, Ready)

Move to Running (drag a card, or click Run) → PATCH /tasks/{id} {status:running}
   → _route_task_execution(task):
       • first-party (agent ∈ LOOM_WORKER_AGENTS) → supervisor.spawn(...) + worker:started
       • external (hermes, …)                     → _drop_inbox_task(...) + progress milestone
                                                     ("Dispatched to <agent> via inbox")
```

`_route_task_execution` **supersedes** Part 1's `_start_worker_for` (the worker-spawn
branch is unchanged; the external branch is new). The PATCH→running hook and the
`worker/start` endpoint both call it.

## API / data changes

- **`POST /dispatch`** — creates an `agent_tasks` row (status **Ready**) assigned to
  `{target_agent}-{project}`; derives `title` from the first line of the instruction;
  maps priority `low/medium/high → 0/1/2`. Returns `{task_id, status: "ready"}`. **No
  inbox drop at dispatch time** (the drop now happens during external routing on Running).
- **`GET /dispatches`** — returns `agent_tasks` for the project mapped to the existing
  `DispatchInfo` shape `{task_id, target_agent, instruction, status, dispatched_at, priority}`
  so `dispatch-history` + `agent-wiring` keep working; `status` is now the 7-state lifecycle,
  `target_agent` is the `assignee`, `dispatched_at` is `created_at`.
- **`registry.create_agent_task`** — accepts an optional explicit `task_id` and an optional
  `status` override; idempotent on the id (`INSERT OR IGNORE`).
- **Router `_handle_task`** — upserts an `agent_tasks` row idempotently (replacing the
  legacy `create_task` call); preserves the dual-write idempotency contract on `agent_tasks`.
- **`LOOM_INBOX_BASE`** — the inbox root (`~/.loom/inbox`) becomes a module global in
  `api.py` so tests redirect it to a temp dir (external routing writes a real file).

## Chat-window semantics for external-agent tasks

- The worker pill reads **"external: <agent>"** (no live subprocess).
- **Run** = (re)drop the inbox `task-*.json`; **Stop** is hidden — you cannot kill an
  autonomous external agent; the user can move the card to Blocked manually.
- The transcript shows the dispatch milestone plus any findings the agent writes that
  reference this `task_id` (findings already carry `task_id`; surfacing them in the feed
  is a follow-up, see Out of scope).

## Out of scope (this addendum)

- Auto-completing an external task when a matching finding arrives (today: manual move to
  Done). Future: `_handle_finding` flips the `agent_task` to Done when the finding's
  `task_id` matches.
- Destructive migration of legacy `tasks` rows into `agent_tasks` (the legacy table is
  abandoned, not migrated).
- A configuration UI for `LOOM_WORKER_AGENTS` (a constant for now).

## Files touched (addendum)

**Daemon:** `daemon/api.py` (`/dispatch` repointed, `/dispatches` mapped,
`_route_task_execution`, `_drop_inbox_task`, `LOOM_WORKER_AGENTS`, `LOOM_INBOX_BASE`),
`daemon/registry.py` (`create_agent_task` optional `task_id`/`status`),
`daemon/router.py` (`_handle_task` upserts `agent_tasks`).
**Dashboard:** `components/dispatch-history.tsx` + `components/agent-wiring.tsx` (lifecycle
status badges / filter), `messages/{en,ar}.json` (lifecycle status labels). The dispatch
modal is unchanged (still POSTs to `/dispatch`).
**Tests:** `tests/test_api.py` (dispatch-creates-agent-task, `/dispatches` mapping,
route-by-assignee external/first-party, fixture redirects `LOOM_INBOX_BASE`),
`tests/test_router.py` (handle_task upsert), `tests/test_registry.py` (explicit-id create).
