# Agentic OS

Unified agent memory fabric. Links all AI coding agents on a single machine through a shared Graphify-powered knowledge graph. Agents communicate via filesystem hooks — no SDK, no API client, no auth required. A Next.js dashboard provides the control plane for monitoring, querying, and managing agents.

**Status:** v0.1.0 — daemon + dashboard working, 22 tests passing, smoke-tested end-to-end.

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
│              Agentic OS Daemon (Python)              │
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
| **Watcher** | Monitors `~/.agentic-os/inbox/` via watchdog. Detects new/modified files and routes them. |
| **Router** | Core dispatcher. Processes register.json, heartbeat.json, finding-*.md, decision-*.md. Moves processed files to `.processed/`. |
| **Graph Engine** | Async wrapper around Graphify. Builds, updates, queries knowledge graphs. CPU-bound work runs in a thread pool. |
| **Agent Registry** | SQLite database tracking agents, projects, capabilities, heartbeat status, and activity. |

### Key Design Principles

- **Single process** — one `agentic-os` command starts everything. No IPC, no microservices.
- **SQLite for state** — agent registry, project metadata. File lives in `~/.agentic-os/state.db`. Zero setup.
- **Graphify in-process** — `import graphify`, not subprocess spawning. Build/update/query via thread pool.
- **WebSocket push** — dashboard gets live updates on graph changes, agent status, errors. No polling.
- **Per-project isolation** — each project gets its own inbox subdirectory and `graphify-out/`. No cross-contamination.

---

## Project Structure

```
agentic-os/
├── daemon/                    # Python package
│   ├── __init__.py
│   ├── main.py               # CLI entry point (uvicorn)
│   ├── api.py                # FastAPI routes + WebSocket
│   ├── models.py             # Pydantic schemas
│   ├── registry.py           # SQLite agent/project CRUD
│   ├── graph_engine.py       # Graphify async wrapper
│   ├── watcher.py            # Watchdog inbox monitor
│   └── router.py             # Inbox event dispatcher
├── dashboard/                # Next.js 15 app
│   ├── app/
│   │   ├── layout.tsx        # Root layout + sidebar
│   │   ├── page.tsx          # Project overview
│   │   └── projects/[id]/
│   │       ├── page.tsx      # Project detail
│   │       └── graph/page.tsx # Graph explorer
│   ├── components/
│   │   ├── sidebar.tsx
│   │   ├── project-card.tsx
│   │   ├── graph-stats.tsx
│   │   ├── agent-badge.tsx
│   │   └── activity-feed.tsx
│   └── lib/
│       ├── api.ts            # Typed fetch wrapper
│       └── use-websocket.ts  # WebSocket hook
├── tests/
│   ├── test_api.py           # 10 API integration tests
│   ├── test_registry.py      # 5 registry unit tests
│   ├── test_graph_engine.py  # 3 graph engine tests
│   ├── test_router.py        # 3 router tests
│   └── test_watcher.py       # 1 watcher test
├── scripts/
│   └── smoke-test.sh         # End-to-end test
├── docs/
│   ├── plans/                # Implementation plan
│   └── superpowers/specs/    # Design spec
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
git clone git@github.com:mohamedhusseinios/agentic-os.git
cd agentic-os

# Python daemon
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Dashboard
cd dashboard && npm install
```

### Run

```bash
# Terminal 1: start the daemon
agentic-os --port 8472

# Terminal 2: start the dashboard
cd dashboard && npm run dev
```

Open **http://localhost:3000**

---

## Filesystem Protocol — How Agents Connect

Agents communicate with Agentic OS exclusively through the filesystem. No SDK, no API client, no authentication required. Every agent writes to `~/.agentic-os/inbox/<project>/`.

### Directory Layout

```
~/.agentic-os/
├── inbox/                  ← agents write here
│   ├── noor/               ← per-project subdirectory
│   │   ├── register.json       ← agent self-registration
│   │   ├── heartbeat.json      ← liveness ping
│   │   ├── finding-*.md        ← code analysis findings
│   │   └── decision-*.md       ← architecture decisions
│   ├── mailo/
│   └── agentfiy/
├── state.db               ← SQLite agent registry
└── daemon.log             ← daemon logs
```

### File Types

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

Written periodically (recommended every ~60s). Agent is marked offline if no heartbeat in 5 minutes.

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

Free-form markdown with YAML frontmatter. The daemon extracts entities and feeds them to Graphify. If `files` references code files, it triggers an incremental graph update.

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

Structured ADRs. Indexed as graph nodes linked to affected code entities.

### Processing Rules

1. **Atomic per file** — each file processed independently. Failure doesn't block others.
2. **Processed → archived** — after processing, file moves to `.processed/`. Keeps inbox clean.
3. **Deduplicate** — same file re-written overwrites previous extracted nodes.
4. **Rate limit** — max 1 Graphify build per project per 30 seconds. Rapid writes are batched.

---

## API Endpoints

All endpoints on `http://localhost:8472`.

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check (daemon status, graphify available, watcher running) |
| `GET` | `/api/projects` | List all tracked projects with node/edge/community/agent counts |
| `GET` | `/api/projects/:id` | Project detail with graph stats and agent list |
| `GET` | `/api/projects/:id/graph` | Graph stats only (nodes, edges, communities) |
| `GET` | `/api/projects/:id/query?q=` | Natural language query of the knowledge graph |
| `GET` | `/api/projects/:id/agents` | List agents for a project with status and capabilities |
| `POST` | `/api/projects/:id/rebuild` | Force a full graph rebuild |
| `WS` | `/ws` | Live event stream (graph updates, agent status, errors) |

### WebSocket Events (Server → Client)

| Event | Payload | When |
|-------|---------|------|
| `agent:online` | `{agent, capabilities}` | Agent registers |
| `agent:offline` | `{agent, reason}` | Agent heartbeat times out |
| `graph:updated` | `{nodes_added, edges_added, status}` | Build/update completes |
| `finding:ingested` | `{file, type}` | Finding processed |
| `error` | `{file, message}` | Processing failure |

---

## Dashboard

| Route | Screen | What it shows |
|-------|--------|---------------|
| `/` | Project Overview | Cards for all tracked projects with node/edge/community counts, active agent badges |
| `/projects/[id]` | Project Detail | Graph stats, agent list with status dots, live activity feed |
| `/projects/[id]/graph` | Graph Explorer | Natural language query input + results display, example queries |

Built with Next.js 15 (App Router), Shadcn UI, Tailwind CSS dark theme.

---

## Agent Lifecycle

1. **Registration** — agent writes `register.json` to `inbox/<project>/`
2. **Graph build** — daemon runs full Graphify build on project codebase
3. **Heartbeat** — agent writes `heartbeat.json` every ~60s
4. **Contribution** — agent writes `finding-*.md` or `decision-*.md` as it discovers things
5. **Graph update** — daemon ingests findings, runs incremental updates, persists stats to registry
6. **Deregistration** — agent stops writing heartbeats → marked offline after 5 min
7. **Re-registration** — agent writes new `register.json` → back online, graph stays live

---

## Development

### Running Tests

```bash
source .venv/bin/activate

# All tests (22 passed)
pytest tests/ -v

# Specific module
pytest tests/test_api.py -v
pytest tests/test_registry.py -v
pytest tests/test_router.py -v
pytest tests/test_graph_engine.py -v
pytest tests/test_watcher.py -v
```

### Smoke Test

```bash
bash scripts/smoke-test.sh
```

Starts the daemon, registers a test agent, sends a heartbeat, checks API responses — then cleans up.

### Dashboard

```bash
cd dashboard

# Dev server (hot reload)
npm run dev

# Production build
npm run build
```

### CLI Options

```
agentic-os --help

  --host HOST           Bind host (default: 127.0.0.1)
  --port PORT           Bind port (default: 8472)
  --reload              Enable auto-reload (dev mode)
  --log-level LEVEL      Log level (default: info)
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Malformed JSON | Logged, file moved to `.failed/`, error event pushed via WebSocket |
| Graphify build failure | Logged with stderr, surfaced in API response, event emitted |
| Graphify import failure | Daemon logs warning, continues without graph features (`graphify_available: false`) |
| Watchdog failure | Daemon exits with error code |
| Port conflict | Daemon logs which port is in use |
| Missing project | API returns HTTP 404 with `{"detail": "Project not found"}` |
| Missing query param | API returns HTTP 400 with `{"detail": "Missing query parameter 'q'"}` |
| Watchdog double-fire | File already-moved detection: skipped gracefully |

---

## Dependencies

### Python (daemon)

| Package | Purpose |
|---------|---------|
| `fastapi` + `uvicorn` | REST API + WebSocket server |
| `watchdog` | Filesystem monitoring |
| `graphifyy` | Knowledge graph engine (build, update, query) |
| `pydantic` | Data validation and serialization |
| `aiosqlite` | Async SQLite for agent registry |
| `pyyaml` | YAML frontmatter parsing |

### Node.js (dashboard)

| Package | Purpose |
|---------|---------|
| `next` | React framework (App Router) |
| `shadcn/ui` | Component library (card, badge, input, button, scroll-area) |
| `tailwindcss` | Utility-first CSS |
| `lucide-react` | Icon library |

---

## Out of Scope (v1)

- Multi-machine agent federation
- Agent-to-agent direct messaging
- Task dispatch from dashboard to specific agents
- Graph visualization (HTML graph) in dashboard
- Authentication/authorization
- Payment/subscription integration
- Mobile dashboard
- Launchd/systemd service management

---

## Design Spec

Full design document: [`docs/superpowers/specs/2026-06-25-agentic-os-design.md`](docs/superpowers/specs/2026-06-25-agentic-os-design.md)

Implementation plan: [`docs/plans/2026-06-25-agentic-os-implementation.md`](docs/plans/2026-06-25-agentic-os-implementation.md)
