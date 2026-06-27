# Interactive Kanban Task Board + Autonomous Claude Code Worker — Design

**Date:** 2026-06-27
**Status:** Approved (design) — pending implementation plan
**Related:**
- `docs/plans/2026-06-26-competitor-gap-closure-implementation.md` (Feature 2: Durable Multi-Agent Task Board)
- `docs/superpowers/specs/2026-06-26-agentic-os-dashboard-features-design.md`

---

## 1. Summary

Add a **fully interactive Kanban board** to the Loom OS dashboard for adding, assigning, and managing agent tasks, plus a new **`loom worker`** process that autonomously executes a task with **Claude Code (headless)** when the user moves it to **Running** — working in an **isolated git worktree** until the task finishes, then surfacing the diff for review.

The task *coordination* backend (7-state model, SQLite table, CRUD API, dependency auto-promotion, lifecycle tests) **already exists** from Feature 2 of the competitor-gap plan. This spec covers the two pieces that do **not** exist: the interactive UI, and the execution loop that makes "set a task to Running → an agent does the work" real.

---

## 2. Background: current state

### Already built (verified in code)
- **Models** (`daemon/models.py`): `AgentTaskStatus` (`triage`/`todo`/`ready`/`running`/`blocked`/`done`/`archived`), `AgentTaskCreatePayload`, `AgentTaskRecord` (includes `workspace_path`), `AgentTaskUpdatePayload`.
- **Registry** (`daemon/registry.py`): `create_agent_task`, `get_agent_task`, `update_agent_task`, `list_agent_tasks`, `_all_agent_task_deps_done`, `_row_to_agent_task`. The `agent_tasks` table (with `result` and `workspace_path` columns) and its index are created in `initialize()`.
- **API** (`daemon/api.py`): `POST /api/projects/{id}/tasks` (201), `GET /api/projects/{id}/tasks?status=`, `PATCH /api/projects/{id}/tasks/{task_id}`.
- **Tests**: `test_agent_task_lifecycle_api`, `test_full_task_lifecycle_with_dependencies`, plus 404/empty guards.
- **CLI** (`daemon/main.py`): argparse with a subcommand structure (`start`, `register`, `unregister`, …) and a `KNOWN_SUBCOMMANDS` list — bare args default to `start`.

### Not built (the work in this spec)
1. **Any task UI.** The dashboard only has the older *dispatch* components (`dispatch-modal`, `dispatch-history`, `agent-wiring`). No `task-board.tsx`, no tasks route, no `lib/api.ts` wrappers for agent tasks.
2. **WebSocket events for tasks.** The task endpoints emit nothing, so a board cannot update live.
3. **The execution loop.** No mechanism hands a task to an agent. The inbox is one-directional (agent → daemon); there is no outbox, no claim/poll, nothing that runs work. `workspace_path` is never set.
4. **Dependency *re*-promotion.** Dependents auto-promote to `ready` only at *create* time. Marking a parent `done` later does not unblock children.

---

## 3. Decisions

Three forks were resolved with the user:

| Fork | Decision | Rationale |
|------|----------|-----------|
| How does "the agent starts working" happen? | **Loom ships a worker** (`loom worker`) | Keeps the daemon single-process and the filesystem moat intact; gives a real autonomous loop. |
| What does the worker invoke? | **Claude Code, first-class** (`claude -p` headless, structured output, auto-retain findings) | Richest result capture; turns task work into graph enrichment. |
| Where/how aggressively does it edit? | **Isolated git worktree per task**, diff surfaced for review/merge | Main tree never touched; enables crash recovery; gives `workspace_path` a real job. |

### Ruled out
- **Daemon-inline execution** — breaks the single-process / no-API-keys-in-daemon moat.
- **Third-party-agent outbox** — heavier; the user chose a first-party worker. (The worker is first-party Loom code, so it legitimately uses the daemon's HTTP API; the filesystem-only rule is about *third-party* agents and stays untouched.)

---

## 4. Architecture & data flow

```
┌─────────────┐   PATCH status=running     ┌──────────────┐
│  Dashboard  │ ─────────────────────────► │    Daemon    │  owns task state (SQLite)
│  Kanban UI  │ ◄──── WS task:updated ───── │   FastAPI    │  emits WS events
│  (Tasks tab)│ ◄──── WS task:progress ──── │              │
└─────────────┘                            └──────┬───────┘
       ▲                                          │ GET .../tasks?status=running
       │                                          ▼
       │                                   ┌──────────────┐
       │  (diff / merge via API)           │  loom worker │  registers as an agent
       └──────────────────────────────────│  (1 process) │  git worktree add loom/task-<id>
                                           │              │  claude -p (acceptEdits) in worktree
                                           │              │  parses stream-json → result
                                           │              │  PATCH status=done|blocked
                                           └──────┬───────┘  POST .../progress (live)
                                                  │ writes finding-*.md
                                                  ▼
                                  ~/.loom/inbox/<project>/ → watcher → graph update
```

**Boundaries (single clear purpose each):**
- **Daemon** = source of truth for task state + WS fan-out. No execution, no keys.
- **Worker** = execution only. Stateless beyond the task it's running; all durable state lives in the daemon + the worktree.
- **Dashboard** = control plane. Renders board state, issues mutations, never talks to the worker directly.

---

## 5. Component A — Daemon changes

All small; the heavy lifting (models/registry/endpoints) already exists.

### A1. Emit WebSocket events from task endpoints
Add a helper in `api.py` that enqueues onto `router.events` (guarded for test mode where `router`/broadcast may be absent):
- `POST .../tasks` → `task:created` (data = full `AgentTaskRecord`).
- `PATCH .../tasks/{id}` → `task:updated` (data = full updated record).

Mirror the existing pattern (`WsEvent(event=..., project=..., data=...)` → `router.events`).

### A2. Dependency re-promotion on completion
When a task transitions to `done`, re-evaluate dependents: any `todo` task whose dependencies are now all `done` is promoted to `ready`, emitting `task:updated` for each. New registry method `promote_ready_dependents(task_id)`, called from the `PATCH` handler when the new status is `done`.

### A3. Live progress endpoint
`POST /api/projects/{id}/tasks/{task_id}/progress` with `{message}` → emits a transient `task:progress` WS event `{ id, message }`. Not persisted (keeps the schema stable); it exists purely to make "the agent is working" visible on the board.

### A4. Worktree diff / merge endpoints
- `GET /api/projects/{id}/tasks/{task_id}/diff` → returns the worktree branch diff (`git -C <workspace_path> diff <base>...HEAD`, or name-status + patch).
- `POST /api/projects/{id}/tasks/{task_id}/merge` → merges `loom/task-<id>` into the project's base branch (and optionally removes the worktree). Returns merge result. Conflicts are reported, not forced.

These run `git` via subprocess (matching how Graphify is already invoked as a subprocess), off the event loop via `asyncio.to_thread`.

---

## 6. Component B — `loom worker`

New module `daemon/worker.py` + a `worker` subcommand in `daemon/main.py` (added to `KNOWN_SUBCOMMANDS`). Optional `daemon/worktree.py` for git helpers.

### B1. Identity & startup
`loom worker --project <id> --agent <name> [--base-url http://127.0.0.1:8472] [--model ...] [--max-turns N] [--poll 2.5]`
- On start, **register as an agent** (reuse the existing registration path) so the worker appears as an assignable, online agent in the UI and can be a task `assignee`.
- Heartbeat while alive (reuse existing heartbeat) so the board can show the worker online.

### B2. Poll & claim loop
Every `--poll` seconds:
1. `GET /api/projects/{id}/tasks?status=running`.
2. Filter to `assignee == my_agent_id` and not already in-flight (in-memory set).
3. Take **one** task (V1 = one at a time), mark it in-flight, execute.

*Auto-assign note:* assignment is always resolved to a **concrete `assignee` (agent_id) at create/assign time** (the dashboard maps "Auto" → first online agent before sending). Tasks are never left with a null assignee once queued, so the `assignee == my_agent_id` filter always works.
*Concurrency note (V1):* one worker per agent identity, one task at a time. Atomic multi-worker claim is out of scope (see §13).
*Stuck note:* a `running` task with no online worker simply waits; the board shows assignee online-state so the user can tell. No auto-revert in V1.
*Crash recovery:* if a worker dies mid-run, the task stays `running` (not in any worker's in-flight set), so a restarted worker re-claims it; the worktree/branch persists, and `--resume <session_id>` can continue the same Claude session.

### B3. Worktree lifecycle
- Base = the project's registered `project_path` (assumed a git repo — Loom/Graphify already assume this; if not, the task → `blocked` with a clear message).
- Create: `git -C <project_path> worktree add <workspace_path> -b loom/task-<id>` from the base branch (configurable; default current `HEAD`). `workspace_path = ~/.loom/workspaces/<project>/task-<id>` (outside the repo to avoid nesting). Persist `workspace_path` on the task.
- Run Claude with `cwd = workspace_path`.
- Leave the worktree/branch in place on completion (review/merge happens via the API in §A4). Removal happens on merge or archive.

### B4. Claude Code invocation
- Command (exact flags **verified against Claude Code docs at implementation time** — operating principle):
  `claude -p "{instruction}" --output-format stream-json --permission-mode acceptEdits --max-turns {N} --model {model}` with `cwd = workspace_path`. `acceptance_criteria` appended to the prompt (or via `--append-system-prompt`).
- Read `stream-json` line-by-line: assistant text + `tool_use` → throttled `POST .../progress`; final `result` event yields `result`, `session_id`, `num_turns`, `total_cost_usd`, `is_error`.
- Persist `session_id` (in `result` JSON or an in-memory map) for resume.

### B5. Status transitions
- Success (`is_error == false`, exit 0): `PATCH status=done`, `result = <final text + summary>`.
- Failure (non-zero exit, `is_error`, or timeout): `PATCH status=blocked`, `result = <error>`.
- **Resume**: re-running a `blocked` task adds `--resume <session_id>` so it continues the same Claude session (ties to the board's `blocked → running`).

### B6. Auto-retain into the graph
On completion, write `~/.loom/inbox/<project>/finding-<id>.md` (YAML frontmatter `agent/project/timestamp/type` + the agent's summary and any `FOUND:`/`PATTERN:`/`DECISION:` lines). The existing watcher → router → graph-update pipeline indexes it. Working a task makes the project graph smarter.

### B7. Config & safety
- Defaults: `acceptEdits` (edits + reads, no destructive bypass), a `--max-turns` cap, configurable `--allowedTools`, configurable `--model`.
- `--dangerously-skip-permissions` is opt-in only, never default.
- Claude auth comes from the user's own environment/Claude Code login — the **daemon never sees credentials**; only the worker process (owned by the user) does.

---

## 7. Component C — Dashboard

Next.js 16 / React 19. **Read the bundled Next 16 docs before writing** (`dashboard/node_modules/next/dist/docs/`), per `dashboard/AGENTS.md`.

### C1. API wrappers (`lib/api.ts`)
`createAgentTask`, `listAgentTasks`, `updateAgentTask`, `getTaskDiff`, `mergeTask` — typed against `AgentTaskRecord`. (Distinct from the existing `dispatchTask`/`listDispatches`.)

### C2. Live updates
Subscribe via the shared `useWebSocket()` provider to `task:created` / `task:updated` / `task:progress`, filtered by project. Never open a second socket. Optimistic update on drag, reconciled by the echoed `task:updated`.

### C3. Board route & components
- **Route:** `app/[locale]/projects/[id]/tasks/page.tsx` (mirrors the existing `graph` sub-route). Add a tab/link from the project page.
- **`components/task-board.tsx`:** 5 columns — **Todo · Ready · Running · Blocked · Done** — + an **Archived** toggle. (`triage` is the new-task intake.) Drag-and-drop via **`@dnd-kit`**; a card status-menu is the accessible fallback. Drop → `PATCH status`; dropping into **Running** is what starts the agent.
- **`components/new-task-modal.tsx`:** mirrors `dispatch-modal`. Fields: title, instruction, assignee (agent dropdown incl. the worker; "Auto" resolves to the first online agent and is sent as a concrete `assignee`, never null — see §6 B2), priority, optional dependencies (multi-select of existing tasks), optional acceptance criteria.
- **`components/task-detail-drawer.tsx`:** title, status, assignee, instruction, acceptance criteria, dependencies (with their statuses), **live output/result**, **worktree branch + diff + Merge button**, timestamps. Actions: reassign, change status, archive, **retry** (blocked → resume).

### C4. i18n
Add a `tasks.*` namespace to **both** `messages/en.json` and `messages/ar.json` (RTL).

---

## 8. WebSocket event contract

| Event | When | `data` |
|-------|------|--------|
| `task:created` | task created | full `AgentTaskRecord` |
| `task:updated` | status/assignee/result change, or re-promotion | full updated `AgentTaskRecord` |
| `task:progress` | worker emits a step (transient) | `{ id, message }` |

All include `project` and `timestamp` (existing `WsEvent` shape).

---

## 9. Data model

No schema migration required — `agent_tasks` already has every needed column, including `result` and `workspace_path`. New behavior only:
- The **worker** sets `workspace_path` (worktree dir) and `result`.
- `session_id` is carried in the run (not a column in V1); persisted inside `result` JSON if needed for resume.

---

## 10. Worktree & merge strategy

- Branch per task: `loom/task-<id>`, worktree at `~/.loom/workspaces/<project>/task-<id>`.
- **Done** = a branch with a reviewable diff (not just a status flip). The detail drawer shows the diff and offers **Merge into base** (manual; conflicts reported, never force).
- Cleanup (`git worktree remove`) on merge or archive. Orphan worktrees from killed workers are recoverable (branch persists) and cleanable via archive.

---

## 11. Security & safety

- Autonomous edits are confined to an **isolated worktree**; the user's main checkout is never modified by the agent.
- Daemon holds **no credentials**; execution + Claude auth live only in the user-owned worker process.
- Safe defaults: `acceptEdits`, bounded `--max-turns`, scoped `--allowedTools`. Full bypass is explicit opt-in.
- Merge is always a deliberate user action.

---

## 12. Testing strategy

- **`tests/test_worker.py`** (new): mock the `claude` and `git` subprocesses. Cover: claims a `running` task assigned to it → creates worktree → sets `workspace_path` → success path sets `done` + writes a `finding-*.md`; failure path sets `blocked`; ignores tasks not assigned to it. **No real API/network calls.**
- **`tests/test_api.py`** (extend): `task:created`/`task:updated` enqueued on create/patch; dependency re-promotion on `done`; progress endpoint emits `task:progress`; diff/merge endpoints (git mocked or a temp repo).
- **Green bar:** the existing 38 tests must stay passing.
- **Dashboard:** `npm run lint`; manual board walkthrough (create → assign → drag to Running → watch progress → Done → view diff → merge).

---

## 13. Out of scope (future)

- Parallel workers + atomic multi-worker claim (conditional `PATCH`).
- Auto-merge / auto-PR on done.
- Auto-assign load-balancing beyond "first online agent".
- Token/cost dashboards and rich trace timelines (Feature 6 territory).
- Third-party-agent outbox protocol.
- Automatic worktree GC policies.
- Multi-project single worker.

---

## 14. File inventory

**New**
- `daemon/worker.py` — worker loop, Claude invocation, output parsing, auto-retain.
- `daemon/worktree.py` — git worktree create/diff/merge/remove helpers (or folded into `worker.py`).
- `tests/test_worker.py`
- `dashboard/components/task-board.tsx`
- `dashboard/components/new-task-modal.tsx`
- `dashboard/components/task-detail-drawer.tsx`
- `dashboard/app/[locale]/projects/[id]/tasks/page.tsx`

**Modified**
- `daemon/main.py` — `worker` subcommand (+ `KNOWN_SUBCOMMANDS`).
- `daemon/api.py` — WS events on task endpoints; `progress`, `diff`, `merge` endpoints; call re-promotion on `done`.
- `daemon/registry.py` — `promote_ready_dependents`; set `workspace_path`.
- `dashboard/lib/api.ts` — agent-task wrappers + diff/merge.
- `dashboard/messages/en.json`, `dashboard/messages/ar.json` — `tasks.*` strings.
- `dashboard/package.json` — `@dnd-kit/*`.
- `pyproject.toml` — only if a new dep is needed (git + claude are subprocesses; expected: none).
- `README.md` / `CLAUDE.md` — document `loom worker` + the Tasks board.
- `tests/test_api.py` — new assertions above.

---

## 15. Verification checklist

- [ ] Existing 38 tests stay green.
- [ ] No new infrastructure (no Docker/Neo4j/external DB); git + claude are subprocesses.
- [ ] Filesystem inbox protocol preserved (worker auto-retain writes `finding-*.md`; daemon stays first-party-only over HTTP).
- [ ] Single-process daemon unchanged; the worker is a separate, optional process.
- [ ] Per-project isolation intact (tasks, worktrees, workers all project-scoped).
- [ ] `task:created` / `task:updated` / `task:progress` emitted and consumed live.
- [ ] Dashboard dark theme + RTL strings in both locales.
- [ ] Claude Code headless flags/output schema confirmed against official docs before coding the worker.
- [ ] Autonomous edits confined to an isolated worktree; main tree untouched; merge is user-initiated.
