# Task Board & Worker

Every project has a **Tasks** tab in the dashboard with a Kanban board and an optional worker process that executes tasks in isolated git worktrees.

## Kanban Board

The board has five visible columns — **Todo · Ready · Running · Blocked · Done** — and an archived state for finished work. Create a task, assign it to any registered agent, and drag the card between columns to advance it.

Moving a card to **Running** triggers execution. Moving it back to **Todo** or **Blocked** pauses it.

## 7-State Lifecycle

```
triage → todo → ready → running → blocked → done → archived
```

| State | Meaning |
|-------|---------|
| `triage` | Just created; not yet assigned or prioritised |
| `todo` | Assigned to an agent; waiting on dependencies |
| `ready` | All dependencies complete; ready to execute |
| `running` | Worker has picked it up and is executing |
| `blocked` | Stalled; needs human intervention |
| `done` | Completed; diff available for review |
| `archived` | Finished and filed away; removed from the board |

**Dependency auto-promotion:** when all of a task's dependencies reach `done`, the task automatically advances from `todo` to `ready` — no manual drag required.

## Worker

The worker is a separate, optional process that executes tasks assigned to a given agent. The project directory must be a git repository — the worker creates an isolated branch for each task.

### Running

```bash
# 1. Start the daemon (if not already running)
loom --port 8472

# 2. Start a worker for a project (separate terminal)
loom worker --project my-project --agent claude-code --project-path /abs/path/to/my-project

# Optional: cap spend per task (default $5)
loom worker --project my-project --agent claude-code --project-path /abs/path/to/my-project --max-budget-usd 10

# 3. In the dashboard → project's Tasks tab → create a task, assign it to
#    the worker's agent, and drag the card to "Running".
#    The worker runs the agent headless in an isolated git worktree
#    (branch loom/task-<id>) and moves the card to Done with a reviewable diff.
```

### Safety Model

| Concern | Safeguard |
|---------|-----------|
| **Your main checkout** | The worker never touches it. Each task runs in a `git worktree` on branch `loom/task-<id>` — a fully isolated copy. |
| **Runaway spend** | `--max-budget-usd` caps API cost per task (defaults to $5). |
| **Credentials** | The daemon holds no API keys. Only the user-run worker process invokes agents. |
| **Merging** | The worker never merges. When a task reaches `done`, you review the diff in the task detail drawer and merge as an explicit action. |
| **Knowledge retention** | A finished task's findings are automatically contributed as a finding into the project's knowledge graph. |

### How It Works

1. Worker polls the daemon for `ready` tasks assigned to its agent
2. On picking up a task, creates a `git worktree` on branch `loom/task-<id>`
3. Runs the agent headless in the isolated worktree with budget enforcement
4. On completion, moves the task to `done`, writes findings to the knowledge graph
5. Cleans up the worktree

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/projects/:id/tasks` | Create a task |
| `GET /api/projects/:id/tasks` | List tasks (filter by status) |
| `GET /api/projects/:id/tasks/:taskId` | Get task detail |
| `PATCH /api/projects/:id/tasks/:taskId` | Update task status/metadata |
| `POST /api/projects/:id/dispatch` | Dispatch a task to an agent |
| `GET /api/projects/:id/dispatches` | List recent dispatches |

## WebSocket Events

| Event | When |
|-------|------|
| `task:created` | Task created |
| `task:updated` | Status changed |
| `task:completed` | Worker finishes task |
| `agent:dispatched` | Task dispatched to agent |
