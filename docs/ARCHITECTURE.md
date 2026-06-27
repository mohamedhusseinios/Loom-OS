# Loom OS Architecture

## Overview

Loom OS is a **two-process system**: a Python daemon and a Next.js dashboard. They communicate over REST + WebSocket on localhost.

```
Browser :3000 ──▶  ┌──────────────────────────────────┐
                   │       Next.js Dashboard          │
                   │  React 19 · Shadcn · Tailwind    │
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

## Daemon (`daemon/`)

Python package serving the `loom` CLI. FastAPI + uvicorn on `127.0.0.1:8472`.

### Module Map & Data Flow

```
watcher.py   watchdog observer on ~/.loom/inbox (recursive). Extracts <project>
             from the path, marshals events onto the asyncio loop via
             run_coroutine_threadsafe.
   ↓ (project, filepath)
router.py    Router.handle_file dispatches by filename to _handle_* methods,
             then moves the file to .processed/. Emits WsEvents onto an
             asyncio.Queue. Rate-limits graph updates to 1 / 30s / project.
   ↓
registry.py  AgentRegistry: aiosqlite over ~/.loom/state.db. Tables: agents,
             projects, tasks. CRUD + graph-stat persistence.
graph_engine.py  GraphEngine: build/update/query/stats/topology/communities/flows.
api.py       FastAPI routes (read module globals) + WebSocket fan-out.
models.py    All Pydantic schemas (inbox payloads, registry models, WS events).
```

`api.py`'s `_broadcast_events()` drains `router.events` and pushes each `WsEvent` to all connected WebSocket clients.

### Module Details

| Module | Responsibility |
|--------|---------------|
| `watcher.py` | watchdog file observer; routes events from the filesystem into the asyncio loop |
| `router.py` | Core dispatcher — processes inbox files by type, triggers graph updates, emits WS events |
| `registry.py` | SQLite CRUD (aiosqlite): agents, projects, tasks, capabilities, graph stats |
| `graph_engine.py` | Graphify CLI wrapper; builds/updates/queries via subprocess on a thread pool |
| `api.py` | FastAPI application: REST endpoints, `/ws` WebSocket, lifespan management |
| `models.py` | Pydantic schemas for all data (inbox payloads, registry entities, WS events) |
| `worker.py` | Task worker CLI: polls for tasks, executes in isolated git worktrees |
| `worktree.py` | Git worktree lifecycle management for task isolation |
| `shared_context.py` | Auto-generates `.loom/SHARED_CONTEXT.md` with graph stats and findings |
| `project_knowledge.py` | Project knowledge aggregation and retrieval |
| `known_agents.py` | Agent deduplication and recognition across registrations |
| `mcp_server.py` | MCP (Model Context Protocol) server entry point (`loom-mcp`) |

### Additional Modules (v0.1+)

| Module | Responsibility |
|--------|---------------|
| `ingest.py` | Multi-format document ingestion |
| `extractors.py` | Content extraction pipelines |
| `temporal.py` | Temporal tracking of project changes |
| `traces.py` | Execution trace collection |
| `sessions.py` | Session management and history |
| `snapshots.py` | Project state snapshotting |
| `recall.py` | Knowledge recall and retrieval |
| `patterns.py` | Pattern detection across projects |
| `embeddings.py` | Vector embedding generation |
| `evals.py` | Evaluation framework |
| `audit.py` | Audit trail and logging |

## Design Principles

- **Single process** — one `loom` command starts everything. No IPC, no microservices.
- **SQLite for state** — agent registry, project metadata, dispatched tasks. File lives at `~/.loom/state.db`. Zero setup.
- **Graphify via CLI subprocess** — the daemon shells out to `graphify` on a thread pool. An `import graphify` check only gates availability; actual work is subprocess calls.
- **WebSocket push** — dashboard gets live updates on graph changes, agent status, dispatches, and errors. No polling.
- **Per-project isolation** — each project has its own inbox subdirectory and `graphify-out/`. No cross-contamination.
- **Module-global singletons** — `api.py` holds registry, graph engine, router, watcher as module-level globals; route handlers read them directly. Tests inject temp-backed versions.
- **Idempotent task dispatch** — dual-write (inbox file + registry row) with `INSERT OR IGNORE` ensures the watcher reprocessing a file is a safe no-op.
- **Explicit error mapping** — handlers raise `HTTPException` (404, 400, 409) rather than returning `(body, status)` tuples.

## Dashboard (`dashboard/`)

Next.js 16 App Router + React 19. Talks to the daemon over REST (`localhost:8472`) + one shared WebSocket.

See [Dashboard Guide](DASHBOARD.md) for the full reference.

## Dependencies

### Python

| Package | Purpose |
|---------|---------|
| `fastapi` + `uvicorn` | REST API + WebSocket server |
| `watchdog` | Filesystem monitoring |
| `graphifyy` | Knowledge graph engine (invoked as CLI subprocess) |
| `pydantic` | Data validation and serialization |
| `aiosqlite` | Async SQLite for the registry |
| `pyyaml` | YAML frontmatter parsing |

Dev: `pytest`, `pytest-asyncio`, `httpx`.

### Node.js

| Package | Purpose |
|---------|---------|
| `next` | React framework (App Router) |
| `react` / `react-dom` | React 19 |
| `next-intl` | Internationalization (en/ar, RTL) |
| `shadcn` + `@base-ui/react` | Component primitives |
| `tailwindcss` (v4) | Utility-first CSS |
| `cytoscape` + `cytoscape-cose-bilkent` | Graph visualization |
| `lucide-react` | Icon library |
