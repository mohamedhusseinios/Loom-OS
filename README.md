<div align="center">

<img src="docs/branding/loom-icon-warp-256.png" alt="Loom OS" width="120" height="120" />

# Loom OS

**Unified agent memory fabric**

</div>

Weaves all your AI coding agents into a shared Graphify-powered knowledge graph. Agents communicate via filesystem hooks — no SDK, no API client, no auth required. A Next.js dashboard provides the control plane.

**Status:** v0.1.0 — daemon + dashboard working, 38 tests passing, smoke-tested end-to-end. Includes project CRUD + discovery, an interactive (Cytoscape) graph explorer, agent management with task dispatch, and a bilingual (en/ar) dashboard.

> The product is **Loom OS**. The CLI command and Python package are **`loom`**, and the GitHub repo and design/plan docs are named **`agentic-os`** — same project, different identifiers.

---

## Architecture

```
Browser :3000 ──▶  ┌──────────────────────────────────┐
                   │       Next.js Dashboard          │
                   │  React SPA · Shadcn · Tailwind   │
                   └──────────────┬───────────────────┘
                                  │ REST + WebSocket
                                  │ localhost:8472
┌─────────────────────────────────┼───────────────────┐
│                  Loom Daemon (Python)                │
│  ┌────────────┐  ┌───────────┐  ┌────────────────┐  │
│  │  Watcher   │  │  Router   │  │  Graph Engine  │  │
│  │ (watchdog) │  │(dispatcher│  │   (graphify)   │  │
│  └─────┬──────┘  └─────┬─────┘  └───────┬────────┘  │
│        │               │                │           │
│  ┌─────┴───────────────┴────────────────┴─────────┐  │
│  │           Agent Registry (SQLite)              │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
     ▲                  ▲                  ▲
     │                  │                  │
┌────┴────┐        ┌────┴────┐        ┌────┴────┐
│ ~/inbox │        │ ~/inbox │        │ ~/inbox │
│  /noor  │        │ /mailo  │        │/agentfiy│
└─────────┘        └─────────┘        └─────────┘
  Claude Code         Codex              Hermes
```

### Components

| Component | Role |
|-----------|------|
| **Watcher** | Monitors `~/.loom/inbox/` via watchdog. Detects new/modified files and routes them. |
| **Router** | Core dispatcher. Processes `register.json`, `heartbeat.json`, `finding-*.md`, `decision-*.md`, `task-*.json`. Moves processed files to `.processed/` and emits WebSocket events. |
| **Graph Engine** | Wrapper around the Graphify CLI. Builds, updates, and queries knowledge graphs; reads stats from each project's `graphify-out/graph.json`. Subprocess work runs in a thread pool. |
| **Agent Registry** | SQLite database tracking agents, projects, tasks, capabilities, heartbeat timestamps, and graph stats. |

### Key Design Principles

- **Single process** — one `loom` command starts everything. No IPC, no microservices.
- **SQLite for state** — agent registry, project metadata, dispatched tasks. File lives in `~/.loom/state.db`. Zero setup.
- **Graphify via CLI subprocess** — the daemon shells out to the `graphify` CLI (`graphify <path>`, `--update`, `query`) on a thread pool. An `import graphify` check only gates availability (`graphify_available` in `/api/health`); the actual build/update/query work is subprocess calls.
- **WebSocket push** — dashboard gets live updates on graph changes, agent status, dispatches, and errors. No polling.
- **Per-project isolation** — each project gets its own inbox subdirectory and `graphify-out/`. No cross-contamination.

---

## Project Structure

```
agentic-os/                       # repo dir (package/product is "loom")
├── daemon/                       # Python package — the Loom daemon
│   ├── main.py                   # CLI entry point (`loom`), launches uvicorn
│   ├── api.py                    # FastAPI routes + WebSocket + app lifespan
│   ├── models.py                 # Pydantic schemas (inbox, registry, WS events)
│   ├── registry.py               # SQLite agent/project/task CRUD (aiosqlite)
│   ├── graph_engine.py           # Graphify CLI wrapper (subprocess on a thread)
│   ├── router.py                 # Inbox event dispatcher → registry + graph + WS
│   └── watcher.py                # watchdog inbox monitor
├── dashboard/                    # Next.js 16 app (App Router, React 19)
│   ├── app/
│   │   ├── layout.tsx            # Root passthrough layout
│   │   └── [locale]/             # Locale-segmented routes (en, ar)
│   │       ├── layout.tsx        # <html dir>, fonts, providers
│   │       ├── page.tsx          # Project overview
│   │       └── projects/[id]/
│   │           ├── page.tsx          # Project detail
│   │           ├── graph/page.tsx    # Cytoscape graph explorer
│   │           └── agents/page.tsx   # Agent management + dispatch
│   ├── components/               # Feature + UI components (graph-canvas, dispatch-modal, …)
│   │   └── ui/                   # shadcn primitives
│   ├── i18n/                     # next-intl routing / request / navigation
│   ├── messages/                 # en.json, ar.json translation bundles
│   ├── lib/
│   │   ├── api.ts                # Typed REST client (localhost:8472)
│   │   └── use-websocket.tsx     # Shared WebSocket provider/hook
│   └── proxy.ts                  # next-intl locale middleware (was middleware.ts pre-Next 16)
├── tests/                        # pytest suite: api, registry, graph_engine, router, watcher
├── scripts/
│   └── smoke-test.sh             # End-to-end test
├── run.sh                        # Single-command full-stack launcher
├── docs/
│   ├── plans/                    # Implementation plans
│   ├── superpowers/specs/        # Design specs
│   └── reports/                  # Competitor analysis
├── pyproject.toml
└── README.md
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- [Graphify](https://github.com/nousresearch/graphify) installed (`pip install graphifyy`)

### Install

```bash
git clone https://github.com/mohamedhusseinios/agentic-os.git
cd agentic-os

# Python daemon
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Dashboard
cd dashboard && npm install
```

### Run

```bash
# Single command — starts daemon + dashboard, stops both on Ctrl+C
./run.sh
```

| What | Where |
|------|-------|
| Daemon | `http://127.0.0.1:8472` |
| Dashboard | `http://localhost:3000` |

Or start each manually:

```bash
# Terminal 1: daemon only
loom --port 8472

# Terminal 2: dashboard only
cd dashboard && npm run dev
```

Open **http://localhost:3000**

---

## Filesystem Protocol — How Agents Connect

Agents communicate with Loom exclusively through the filesystem. No SDK, no API client, no authentication required. Every agent writes to `~/.loom/inbox/<project>/`.

### Directory Layout

```
~/.loom/
├── inbox/                  ← agents write here
│   ├── noor/               ← per-project subdirectory
│   │   ├── register.json       ← agent self-registration
│   │   ├── heartbeat.json      ← liveness ping
│   │   ├── finding-*.md        ← code analysis findings
│   │   ├── decision-*.md       ← architecture decisions
│   │   ├── task-*.json         ← dispatched task (daemon → agent)
│   │   └── .processed/         ← files moved here after processing
│   ├── mailo/
│   └── agentfiy/
├── state.db               ← SQLite registry (agents, projects, tasks)
└── daemon.log             ← daemon logs
```

### File Types (Agent → Daemon)

#### `register.json` — Agent joins a project

```json
{
  "agent": "claude-code",
  "version": "2.1.190",
  "project": "noor",
  "project_path": "/Users/mohamedabdulrahman/mohamed-hussien/my-projects/Noor",
  "capabilities": ["code-analysis", "refactoring"]
}
```

Written once when an agent starts working on a project. The daemon creates the project entry in its registry and queues an initial Graphify full build.

#### `heartbeat.json` — Agent liveness

```json
{
  "agent": "claude-code",
  "project": "noor",
  "status": "analyzing auth module",
  "timestamp": "2026-06-25T14:30:00Z"
}
```

Written periodically (recommended every ~60s). Refreshes the agent's `last_heartbeat` and keeps it `online`.

#### `finding-*.md` — Knowledge contributions

```markdown
---
agent: claude-code
project: noor
type: code-analysis
files: [src/pipeline.py, src/ocr.py]
timestamp: 2026-06-25T14:35:00Z
---
# Auth Module Analysis

The auth pipeline uses JWT with Redis-backed session storage...
```

Free-form markdown with YAML frontmatter. If `files` references code files, it triggers an incremental graph update (rate-limited to one update per project per 30s).

#### `decision-*.md` — Architecture decisions

```markdown
---
agent: codex
project: noor
type: architecture-decision
status: proposed
---
# ADR: Switch to async OCR pipeline

## Context
The current sync OCR blocks the request loop...
```

Structured ADRs, processed as architecture-decision findings.

### File Types (Daemon → Agent)

#### `task-*.json` — Dispatched task

When you dispatch work from the dashboard (`POST /api/projects/:id/dispatch`), the daemon drops a `task-*.json` into the target project's inbox **and** records it in the registry. An agent watching its inbox picks up the file and acts on it.

```json
{
  "type": "task",
  "task_id": "5f3c…",
  "target_agent": "claude-code",
  "instruction": "Review the auth module for race conditions",
  "priority": "high",
  "dispatched_by": "dashboard",
  "timestamp": "2026-06-26T10:00:00Z"
}
```

Task creation is idempotent: the registry row is the source of truth (`INSERT OR IGNORE` on `task_id`), so the watcher reprocessing the same file is a safe no-op and never double-broadcasts.

### Processing Rules

1. **Atomic per file** — each file processed independently. Failure doesn't block others.
2. **Processed → archived** — after successful processing, the file moves to `.processed/`. Keeps the inbox clean.
3. **Deduplicate** — same file re-written overwrites previous extracted nodes.
4. **Rate limit** — at most one incremental Graphify update per project per 30 seconds. Rapid writes are batched.

---

## API Endpoints

All endpoints on `http://localhost:8472`. CORS allows `http://localhost:3000`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check (daemon status, graphify availability, watcher running) |
| `GET` | `/api/discover?path=` | Browse filesystem directories for project discovery (skips dot-dirs, doesn't follow symlinks) |
| `GET` | `/api/projects` | List all tracked projects with node/edge/community/agent counts |
| `POST` | `/api/projects` | Create a tracked project (`{name, path}`) — 201 on success, 409 if already tracked |
| `GET` | `/api/projects/:id` | Project detail with graph stats and agent list |
| `DELETE` | `/api/projects/:id` | Remove a project from tracking |
| `GET` | `/api/projects/:id/graph` | Graph stats only (nodes, edges, communities) |
| `GET` | `/api/projects/:id/graph/topology` | Full node/edge topology for visualization |
| `GET` | `/api/projects/:id/graph/communities` | Community list with sizes (for the graph filter) |
| `GET` | `/api/projects/:id/graph/flows` | Execution flows, ranked by criticality |
| `GET` | `/api/projects/:id/query?q=` | Natural language query of the knowledge graph |
| `GET` | `/api/projects/:id/agents` | List agents for a project with status and capabilities |
| `POST` | `/api/projects/:id/rebuild` | Force a full graph rebuild |
| `POST` | `/api/projects/:id/dispatch` | Dispatch a task to an agent (`{target_agent, instruction, priority?}`) |
| `GET` | `/api/projects/:id/dispatches` | List recent task dispatches (newest first, max 50) |
| `WS` | `/ws` | Live event stream |

### WebSocket Events (Server → Client)

| Event | Payload | When |
|-------|---------|------|
| `agent:online` | `{agent, capabilities}` | Agent registers |
| `agent:dispatched` | `{task_id, target_agent, instruction}` | A task is dispatched to an agent |
| `graph:updated` | `{nodes_added, edges_added, communities, status, error}` | Build/update completes |
| `finding:ingested` | `{file, type}` | Finding / decision processed |
| `project:created` | `{project_id, project_name}` | Project added via the API |
| `project:deleted` | `{project_id}` | Project removed via the API |
| `error` | `{file, message}` | Processing failure |

> Note: there is currently **no** `agent:offline` event or heartbeat-timeout sweep. `last_heartbeat` is recorded so a future background task can mark stale agents offline, but today an agent stays at its last status until it re-registers.

---

## Dashboard

Built with Next.js 16 (App Router, React 19), Shadcn UI, Tailwind v4, and a dark theme. Routes are locale-segmented under `/[locale]/` (English default, Arabic with RTL).

| Route | Screen | What it shows |
|-------|--------|---------------|
| `/[locale]` | Project Overview | Cards for all tracked projects with node/edge/community counts and active-agent badges; add/remove projects |
| `/[locale]/projects/[id]` | Project Detail | Graph stats, agent list with status dots, live activity feed |
| `/[locale]/projects/[id]/graph` | Graph Explorer | Interactive Cytoscape graph (topology, community filter, flow highlighting, node detail) + natural language query |
| `/[locale]/projects/[id]/agents` | Agent Management | Agent wiring, task dispatch, and dispatch history |

### Internationalization

next-intl drives localization. Locales (`en`, `ar`) live in the URL path; the locale-negotiation middleware is `proxy.ts` (renamed from `middleware.ts` in Next 16). Translation bundles are `messages/en.json` and `messages/ar.json` — add UI strings to both. Arabic renders right-to-left with an Arabic-capable font.

### Live updates

A single shared `WebSocketProvider` (`lib/use-websocket.tsx`) opens one `ws://localhost:8472/ws` connection for the whole app and fans events out to subscribers keyed by event type or `project:<id>`.

---

## Task Board & Worker

### Kanban task board

Every project has a **Tasks** tab in the dashboard. The board follows a Kanban layout with five visible columns — **Todo · Ready · Running · Blocked · Done** — and an archived state for finished work. Create a task from the tab, assign it to any registered agent, and drag the card between columns to advance it.

Moving a card to **Running** is the signal that triggers execution. Moving it back to **Todo** or **Blocked** pauses it.

### 7-state task lifecycle

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

### Running the worker

The worker is a separate, optional process that executes tasks assigned to a given agent. The project directory must be a git repository — the worker creates an isolated branch for each task.

```bash
# 1. Start the daemon (if not already running)
loom --port 8472

# 2. Start a worker for a project (separate terminal)
loom worker --project my-project --agent claude-code --project-path /abs/path/to/my-project

# Optional: cap spend per task (default $5)
loom worker --project my-project --agent claude-code --project-path /abs/path/to/my-project --max-budget-usd 10

# 3. In the dashboard → project's Tasks tab → create a task, assign it to
#    the worker's agent, and drag the card to "Running".
#    The worker runs Claude Code headless in an isolated git worktree
#    (branch loom/task-<id>) and moves the card to Done with a reviewable diff.
```

### Safety model

| Concern | Safeguard |
|---------|-----------|
| **Your main checkout** | The worker never touches it. Each task runs in a `git worktree` on branch `loom/task-<id>` — a fully isolated copy. |
| **Runaway spend** | `--max-budget-usd` caps API cost per task (defaults to $5). The installed Claude CLI has no built-in turn cap; the budget flag is the enforcement point. |
| **Credentials** | The daemon holds no API keys. Only the user-run worker process invokes `claude`. |
| **Merging** | The worker never merges. When a task reaches `done`, you review the diff in the task detail drawer and merge into the project branch as an explicit action. |
| **Knowledge retention** | A finished task's findings are automatically contributed as a finding into the project's knowledge graph, so every completed task enriches the shared fabric. |

---

## Agent Lifecycle

1. **Registration** — agent writes `register.json` to `inbox/<project>/`
2. **Graph build** — daemon runs a full Graphify build on the project codebase
3. **Heartbeat** — agent writes `heartbeat.json` every ~60s; each one refreshes `last_heartbeat` and keeps the agent `online`
4. **Contribution** — agent writes `finding-*.md` or `decision-*.md` as it discovers things
5. **Graph update** — daemon ingests findings, runs incremental updates, persists stats to the registry
6. **Dispatch** — work can be pushed to an agent via the dashboard, landing as a `task-*.json` in its inbox
7. **Re-registration** — a new `register.json` re-affirms online status; graph stats are preserved across re-registration

---

## Development

### Running Tests

```bash
source .venv/bin/activate

# All tests
pytest tests/ -v

# Specific module
pytest tests/test_api.py -v
pytest tests/test_registry.py -v
pytest tests/test_router.py -v
pytest tests/test_graph_engine.py -v
pytest tests/test_watcher.py -v

# Single test
pytest tests/test_api.py::test_health
```

The suite uses `pytest-asyncio` with `asyncio_mode = auto`. API tests inject a temp-backed registry/graph engine into the `daemon.api` module globals and run with the lifespan suppressed (no watcher, no `~/.loom` writes) — see `tests/test_api.py`.

### Smoke Test

```bash
bash scripts/smoke-test.sh
```

Starts the daemon, registers a test agent, sends a heartbeat, checks API responses — then cleans up.

### Dashboard

```bash
cd dashboard

npm run dev      # dev server (hot reload)
npm run build    # production build
npm run lint     # eslint
```

> **Next.js 16 / React 19:** this is newer than most training data. `dashboard/AGENTS.md` instructs reading the relevant guide in `dashboard/node_modules/next/dist/docs/` before writing dashboard code, since APIs and file conventions (e.g. `middleware.ts` → `proxy.ts`) have changed.

### CLI Options

```
loom --help

  --host HOST           Bind host (default: 127.0.0.1)
  --port PORT           Bind port (default: 8472)
  --reload              Enable auto-reload (dev mode)
  --log-level LEVEL     Log level (default: info)
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Malformed JSON / payload | Logged; an `error` event is pushed via WebSocket. The file is left in the inbox (it is only moved to `.processed/` on success). |
| Graphify build/update failure | `RuntimeError` carrying graphify's stderr; surfaced in the `BuildResult.error` / rebuild response and in the `graph:updated` event's `error` field. |
| Graphify not installed | Daemon continues without graph features; `/api/health` reports `graphify_available: false`, and build/query return failed/empty results gracefully. |
| Missing project | API returns HTTP 404 `{"detail": "Project not found"}` |
| Duplicate project | API returns HTTP 409 `{"detail": "Project '...' is already tracked"}` |
| Missing query param | API returns HTTP 400 `{"detail": "Missing query parameter 'q'"}` |
| Invalid / nonexistent path (create or discover) | API returns HTTP 400 |
| Watchdog double-fire / already-moved file | Skipped gracefully (`path.exists()` check + `FileNotFoundError` guard around the move) |

---

## Dependencies

### Python (daemon)

| Package | Purpose |
|---------|---------|
| `fastapi` + `uvicorn` | REST API + WebSocket server |
| `watchdog` | Filesystem monitoring |
| `graphifyy` | Knowledge graph engine (invoked as the `graphify` CLI) |
| `pydantic` | Data validation and serialization |
| `aiosqlite` | Async SQLite for the registry |
| `pyyaml` | YAML frontmatter parsing |

Dev: `pytest`, `pytest-asyncio`, `httpx`. No Python linter is configured.

### Node.js (dashboard)

| Package | Purpose |
|---------|---------|
| `next` | React framework (App Router) |
| `react` / `react-dom` | React 19 |
| `next-intl` | Internationalization (en/ar, RTL) |
| `shadcn` + `@base-ui/react` | Component primitives |
| `tailwindcss` (v4) | Utility-first CSS |
| `cytoscape` + `cytoscape-cose-bilkent` | Graph visualization |
| `lucide-react` | Icon library |

---

## Out of Scope (v1)

- Multi-machine agent federation
- Agent-to-agent direct messaging
- Automatic agent offline detection (heartbeat-timeout sweep)
- Authentication/authorization
- Payment/subscription integration
- Mobile dashboard
- Launchd/systemd service management

---

## Docs

- Design spec: [`docs/superpowers/specs/2026-06-25-agentic-os-design.md`](docs/superpowers/specs/2026-06-25-agentic-os-design.md)
- Dashboard features design: [`docs/superpowers/specs/2026-06-26-agentic-os-dashboard-features-design.md`](docs/superpowers/specs/2026-06-26-agentic-os-dashboard-features-design.md)
- Implementation plan: [`docs/plans/2026-06-25-agentic-os-implementation.md`](docs/plans/2026-06-25-agentic-os-implementation.md)
- Dashboard features plan: [`docs/plans/2026-06-26-dashboard-features-implementation.md`](docs/plans/2026-06-26-dashboard-features-implementation.md)
- Competitor gap-closure plan: [`docs/plans/2026-06-26-competitor-gap-closure-implementation.md`](docs/plans/2026-06-26-competitor-gap-closure-implementation.md)

---

## Brand

Monochrome, geometric. **Warp** (an L woven on a loom) is the primary mark; **Lattice** (an L traced through a knowledge graph) is the alternate. Full asset kit — logos, lockups, favicons, PWA icons, and usage specs — lives in [`docs/branding/`](docs/branding/README.md).

| | Warp (primary) | Lattice (alternate) |
|---|---|---|
| Icon | <img src="docs/branding/loom-icon-warp-256.png" width="64" /> | <img src="docs/branding/loom-icon-lattice-512.png" width="64" /> |

- **Ink** `#141414` · **Paper** `#FFFFFF` · greys `#6F6F6F`, `#E5E5E5`
- **Wordmark** Space Grotesk 600, tracking −3.5%
- The dashboard favicon, PWA manifest, and sidebar logo are wired from this kit.
