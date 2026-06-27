# Multi-Agent Worker Runners — Design

- **Date:** 2026-06-28
- **Status:** Approved (pending spec review)
- **Author:** brainstormed with Claude Code

## Problem

The dashboard task drawer offers a **Run** button for any task with an assignee, but
clicking it only does something when the assignee is `claude-code`. For any other agent
(e.g. `hermes`) the button appears to do nothing: the task stays `running` with a
"No worker / click Run to start one" banner, and the activity log just accumulates
"Dispatched to <agent> via inbox" lines.

### Root cause (verified)

`worker_start` → `_route_task_execution` (`daemon/api.py:634`) gates on:

```python
LOOM_WORKER_AGENTS = {"claude-code"}      # daemon/api.py:46
...
if agent in LOOM_WORKER_AGENTS:
    supervisor.spawn(...)                 # spawn a real `loom worker` subprocess
    ...
else:
    _drop_inbox_task(...)                 # external branch: write task-*.json + log "Dispatched via inbox"
```

Only `claude-code` spawns a worker subprocess. The first-party worker
(`daemon/worker.py`) is hardwired to Claude: `run_claude()` shells out to
`["claude", "-p", ...]` (`daemon/worker.py:43`). So for `hermes` and friends the call
falls through to the filesystem-protocol branch, drops an inbox file nothing consumes,
and returns `{started: true}` — a silent no-op from the user's perspective.

Confirmed live: task `e8df96ac-530` is `running`, assignee `hermes-solo-seller-ecommerce`;
`~/.loom/inbox/` holds dozens of unconsumed `task-*.json` files.

## Goal

Let the dashboard **actually run** non-Claude agents. Wire up every agent CLI installed
on this machine: `claude-code`, `hermes`, `codex`, `gemini-cli`, `copilot-cli`, `aider`.
(`opencode` is registered in the DB but not installed → it gets no runner and stays
external.)

## Non-goals

- Live per-tool progress for non-streaming agents (coarse progress is acceptable in V1).
- Session resume for non-Claude agents.
- A USD budget cap for non-Claude agents (see Safety).
- Multi-task concurrency changes (worker stays one-task-at-a-time).

## Decisions (from brainstorming)

1. **Scope:** all installed CLIs, not just hermes.
2. **Architecture:** declarative runner registry (Approach A), not per-agent classes.
3. **Safety cap:** none added — rely on git-worktree isolation + each agent's own
   defaults. Residual risk documented below.
4. **UI:** include UI gating so Run only appears for runnable agents.

## Architecture

### New module: `daemon/runners.py`

The agent-specific knowledge currently embedded in `run_claude` becomes a registry plus a
single dispatcher. Return type generalizes `ClaudeResult` → `AgentResult`.

```python
@dataclass
class AgentResult:
    text: str
    session_id: str | None      # only Claude populates this
    is_error: bool

# canonical-name -> RunnerSpec
RUNNERS: dict[str, RunnerSpec]

def run_agent(agent, prompt, cwd, model=None, max_budget_usd=5.0,
              resume=None, on_progress=None) -> AgentResult
```

Each `RunnerSpec` carries:
- `binary` — the executable name (from `known_agents.detect_cmd`).
- `build_argv(prompt, model, max_budget_usd, resume)` — produces the argv list.
- `mode` — `"stream-json"` (Claude) or `"stdout"` (everyone else).
- capability flags: `streams_progress`, `supports_resume`, `supports_budget`.

`run_agent` dispatches by `mode`:
- **stream-json:** the existing Claude logic (parse `result`/`assistant` events, emit
  progress). For `claude-code`, `run_agent` delegates to the unchanged `run_claude` so the
  current, well-tested path is byte-for-byte identical.
- **stdout:** `subprocess.Popen`, capture stdout as `text`, exit-code != 0 → `is_error`
  (falling back to stderr for the message, mirroring `run_claude`'s current behavior).

### Verified command table

| agent | binary | argv (V1) | mode |
|-------|--------|-----------|------|
| claude-code | `claude` | `-p <p> --output-format stream-json --verbose --permission-mode acceptEdits --max-budget-usd N [--model M] [--resume S]` | stream-json |
| hermes | `hermes` | `-z <p>` | stdout |
| codex | `codex` | `exec --dangerously-bypass-approvals-and-sandbox <p>` | stdout |
| gemini-cli | `gemini` | `-p <p> --approval-mode yolo` | stdout |
| copilot-cli | `copilot` | `-p <p> --allow-all-tools` | stdout |
| aider | `aider` | `--message <p> --yes-always` | stdout |

Notes:
- `model` is passed only to Claude in V1; other agents use their configured default.
- `aider` makes its own git commit; the worker's subsequent `commit_all` becomes a no-op
  when the tree is already clean — harmless.
- `codex exec` honors the worktree as CWD; `--dangerously-bypass-approvals-and-sandbox`
  is acceptable because the worktree branch is the isolation boundary.

### `daemon/worker.py`

- `process_task` calls `run_agent(self.agent, prompt, cwd=workspace, ...)` instead of
  `run_claude(...)`. All downstream logic (worktree, progress, finding, commit, status)
  is unchanged because it only consumes the neutral result.
- `run_claude` and `ClaudeResult` are **kept** (`ClaudeResult = AgentResult` alias) so the
  existing tests that patch them still pass; `run_agent` routes the claude case through
  `run_claude`.

### `daemon/api.py`

- Replace the hardcoded `LOOM_WORKER_AGENTS = {"claude-code"}` with a set derived from
  `runners.RUNNERS.keys()`. This one change makes `_route_task_execution` spawn a worker
  subprocess for every runnable agent. No other routing logic changes — the dual-write /
  idempotency / external-branch contract for non-runnable agents is preserved.
- New endpoint `GET /api/agents/runnable` → `{"agents": ["claude-code","hermes", ...]}`
  (the registry keys). Tiny, read-only, no registry/DB coupling.

## UI

Files: `dashboard/app/[locale]/projects/[id]/tasks/page.tsx` (parent, owns `workerRunning`
+ `agents` + worker polling) and `dashboard/components/task-detail-drawer.tsx`.

- `lib/api.ts`: add `listRunnableAgents(): Promise<{ agents: string[] }>`.
- The tasks page fetches the runnable set once and derives, for the selected task, whether
  its assignee maps to a runnable agent (match `task.assignee` against the registered
  `agents[].agent_id` to get `agent_name`, then test membership). It passes a new
  `assigneeRunnable: boolean` prop into the drawer (mirrors how `workerRunning` is already
  computed in the parent and passed down).
- Drawer changes:
  - `canRun = !workerRunning && !isDone && !!task.assignee && assigneeRunnable`.
  - When the assignee is **not** runnable, replace the "No worker / click Run" banner with
    a clear note: "`<agent>` is an external agent — Loom can't start it from here. Assign a
    runnable agent (e.g. claude-code) to run from the dashboard." and hide/disable Run.
- New i18n strings in `messages/en.json` and `messages/ar.json` (e.g.
  `TaskDetail.externalAgentTitle`, `TaskDetail.externalAgentBody`).

Net effect: Run spawns a worker for runnable agents and is honestly disabled (with an
explanation) for non-runnable ones — closing the original "did nothing" bug for every
agent type, including `opencode`.

## Safety

- All runners execute with their auto-approve/YOLO flag inside the per-task git worktree
  on branch `loom/task-<id>` — the same posture as Claude's `acceptEdits` today. Changes
  are reviewable via the existing diff endpoint before merge.
- **Residual risk (accepted):** non-Claude agents have no USD cap and no wall-clock
  timeout in V1, so a misbehaving agent can run long or spend freely. Mitigated only by
  worktree isolation and each agent's own defaults. A generic per-task timeout is the
  natural follow-up if this becomes a problem.

## Backward compatibility

- `run_claude` / `ClaudeResult` preserved; `claude-code` path unchanged via delegation.
- `tests/test_worker.py` (patches `run_claude`) stays green.
- Non-runnable agents keep the exact external-dispatch behavior they have today.

## Testing

- `tests/test_runners.py` (new):
  - `build_argv` per agent → exact argv assertions (pure, no subprocess).
  - generic stdout runner against a fake command (e.g. `["printf", "hi"]`) → success;
    a non-zero-exit fake → `is_error` with stderr captured.
  - `run_agent` dispatch: claude routes to `run_claude` (mockable); unknown agent raises.
- `tests/test_api.py`: `LOOM_WORKER_AGENTS` now contains the runnable set; add a test for
  `GET /api/agents/runnable`. Verify a `hermes` assignee on transition-to-running attempts
  a supervisor spawn (supervisor mocked) rather than an inbox drop.
- Manual smoke test (not in CI; needs each agent's auth + spends tokens): assign a trivial
  task to `hermes`, click Run, confirm a worker subprocess executes in the worktree and the
  task reaches `done` with a diff.

## Files touched

- `daemon/runners.py` (new)
- `daemon/worker.py` (call `run_agent`; keep `run_claude`/`ClaudeResult`)
- `daemon/api.py` (derive `LOOM_WORKER_AGENTS`; add `/api/agents/runnable`)
- `dashboard/lib/api.ts` (`listRunnableAgents`)
- `dashboard/app/[locale]/projects/[id]/tasks/page.tsx` (fetch runnable set, pass prop)
- `dashboard/components/task-detail-drawer.tsx` (gating + external-agent note)
- `dashboard/messages/{en,ar}.json` (new strings)
- `tests/test_runners.py` (new), `tests/test_api.py` (additions)

## Future (out of scope)

- Generic per-task wall-clock timeout / cost caps for non-Claude agents.
- Live progress for streaming-capable agents (gemini `stream-json`, codex `--json`).
- Per-agent model selection from the dashboard.
- Session resume where the agent supports it.
