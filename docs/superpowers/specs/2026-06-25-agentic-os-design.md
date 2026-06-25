# Agentic OS — Design Spec

**Date:** 2026-06-25  
**Status:** Design phase  
**Project:** Standalone (separate repo from Agentfiy)

## Overview

**Agentic OS** is a unified agent memory fabric — a daemon that links all AI coding agents on a single machine through a shared knowledge graph powered by Graphify. Agents communicate via filesystem hooks (writing to `~/.agentic-os/inbox/`). A Next.js dashboard provides the control plane for monitoring, querying, and managing agents and their knowledge graphs.

## Design Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Architecture style | Full OS Layer — daemon wraps the machine, agents register with it |
| Interface | Dashboard with Full Control Plane — dispatch, monitor, manage |
| Memory scope | Codebase knowledge only — class structures, dependencies, call graphs, architecture decisions |
| Project location | Standalone repo, separate from Agentfiy |
| Agent connectivity | Filesystem hooks — `~/.agentic-os/inbox/` |
| Implementation stack | Python daemon (FastAPI) + Next.js dashboard + Graphify in-process |

## System Architecture

The Agentic OS is a single Python daemon with four internal components, plus a separate Next.js frontend.

### Component Diagram

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

1. **Watcher** — Monitors `~/.agentic-os/inbox/` using watchdog. Detects new/modified files, validates format, routes to Router.
2. **Router** — Core dispatcher. Processes inbox events: registers agents, queues graph updates, routes findings to Graph Engine.
3. **Graph Engine** — Wraps Graphify Python API. Handles full builds, incremental updates, and semantic ingestion of agent findings. Runs CPU-bound work in thread pool.
4. **Agent Registry** — SQLite database tracking all registered agents, their projects, capabilities, heartbeat status, and activity history.

### Key Design Principles

- **Single process** — one `agentic-os` command starts everything. No IPC, no microservices.
- **SQLite for state** — agent registry, task queue, config. File lives alongside the daemon. Zero setup.
- **Graphify in-process** — `import graphify`, not subprocess. Faster, type-safe.
- **WebSocket push** — dashboard gets live updates on graph changes, agent status, errors. No polling.
- **Per-project isolation** — each project gets its own inbox subdirectory and graphify-out/. No cross-contamination.
- **Thread pool for CPU work** — Graphify extraction runs in `asyncio.to_thread` to keep FastAPI event loop responsive.

## Filesystem Protocol

Agents communicate with the OS exclusively through the filesystem. No SDK, no API client, no authentication required.

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
├── daemon.log             ← daemon logs
└── config.yaml            ← daemon configuration
```

### File Types

#### register.json — Agent joins a project
```json
{
  "agent": "claude-code",
  "version": "2.1.190",
  "project": "noor",
  "project_path": "/Users/mohamedabdulrahman/mohamed-hussien/my-projects/Noor",
  "capabilities": ["code-analysis", "refactoring"]
}
```
Written once when an agent starts working on a project. Daemon creates the project entry in its registry and queues an initial Graphify full build.

#### heartbeat.json — Agent liveness
```json
{
  "agent": "claude-code",
  "project": "noor",
  "status": "analyzing auth module",
  "timestamp": "2026-06-25T14:30:00Z"
}
```
Written periodically (recommended every ~60s). Daemon marks agent as offline if no heartbeat in 5 minutes. Dashboard shows live status from heartbeat.

#### finding-*.md — Knowledge contributions
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
Free-form markdown with YAML frontmatter. Daemon extracts entities and edges, feeds them to Graphify. If `files` references code files, also triggers incremental `graphify --update`.

#### decision-*.md — Architecture decisions
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
Structured ADRs. Daemon indexes them as graph nodes linked to the affected code entities.

### Processing Rules

1. **Atomic per file** — each file processed independently. Failure doesn't block others.
2. **Processed → archived** — after processing, file moves to `.processed/`. Keeps inbox clean.
3. **Deduplicate** — same file re-written overwrites previous extracted nodes.
4. **Rate limit** — max 1 Graphify build per project per 30 seconds. Rapid writes are batched.
5. **Validation** — malformed JSON is logged, moved to `.failed/`, surfaced in dashboard.

## Graphify Integration

### Data Flow

1. **Full Build** — on first agent registration: `graphify <project_path>` extracts AST from entire codebase, producing `graphify-out/graph.json` (structural layer).
2. **Semantic Ingest** — agent findings (finding-*.md) are wrapped as documents and fed to Graphify's semantic extraction, merged into the graph (semantic layer).
3. **Incremental Update** — `graphify <project> --update` when findings reference changed code files. Only new/changed files re-extracted.
4. **Serve** — FastAPI endpoints query `graph.json` directly. Dashboard fetches via REST, gets live updates via WebSocket.

### Graph Engine API (graph_engine.py)

```python
class GraphEngine:
    async def build_project(project_path) -> BuildResult
    async def update_project(project_path, files) -> UpdateResult
    async def ingest_finding(project_path, md_path) -> IngestResult
    async def query(project_path, question) -> QueryResult
    async def get_stats(project_path) -> GraphStats
```

All methods use `asyncio.to_thread` for CPU-bound Graphify operations.

### Key Decisions

- **In-process Graphify** — `import graphify`, not subprocess. Full Python API access.
- **Thread pool for builds** — keeps FastAPI event loop free during extraction.
- **Build-on-register** — first agent triggers full build. Subsequent agents get live graph.
- **Rate-limited updates** — max 1 build/update per project per 30s.
- **Per-project graphs** — each project has independent `graphify-out/`. No cross-project graph merge.

## Dashboard (Next.js)

### Tech Stack
- Next.js 15 App Router
- Shadcn UI components
- Tailwind CSS
- WebSocket for live updates

### Pages

| Route | Screen | Purpose |
|-------|--------|---------|
| `/` | Project Overview | Cards showing all tracked projects with graph stats, active agents |
| `/projects/[id]` | Project Detail | Graph stats, active agents, activity feed |
| `/projects/[id]/graph` | Graph Explorer | Query interface with results display |
| `/projects/[id]/agents` | Agent Management | Agent list with status, history |

### Components

- **Sidebar** — navigation + project list, always visible
- **ProjectCard** — overview card with node/edge counts, agent status
- **GraphStats** — nodes, edges, communities, god nodes display
- **AgentBadge** — online/offline/working status indicator
- **ActivityFeed** — live scrollable event stream
- **GraphQuery** — natural language input + results rendering

### WebSocket Events (Server → Client)

| Event | Payload |
|-------|---------|
| `graph:updated` | `{project, nodes_added, edges_added, agent}` |
| `agent:online` | `{agent, project, capabilities}` |
| `agent:offline` | `{agent, project, reason}` |
| `agent:heartbeat` | `{agent, project, status, timestamp}` |
| `finding:ingested` | `{project, file, type, entities_found}` |
| `error` | `{project, file, message, agent}` |

### Daemon API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/projects` | List all tracked projects |
| GET | `/api/projects/:id/graph` | Graph stats for project |
| GET | `/api/projects/:id/query?q=` | Graphify query |
| GET | `/api/projects/:id/agents` | Active agents on project |
| GET | `/api/projects/:id/activity` | Recent findings and events |
| POST | `/api/projects/:id/rebuild` | Force full graph rebuild |
| WS | `/ws` | Live event stream |

## Project Structure

```
agentic-os/
├── daemon/                ← Python package
│   ├── __init__.py
│   ├── main.py           ← entry point: uvicorn + watchdog
│   ├── watcher.py        ← filesystem monitor
│   ├── router.py         ← event dispatcher
│   ├── graph_engine.py   ← Graphify wrapper
│   ├── registry.py       ← SQLite agent registry
│   ├── api.py            ← FastAPI routes + WebSocket
│   └── models.py         ← Pydantic schemas
├── dashboard/            ← Next.js app
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   └── projects/[id]/
│   │       ├── page.tsx
│   │       ├── graph/page.tsx
│   │       └── agents/page.tsx
│   ├── components/
│   │   ├── sidebar.tsx
│   │   ├── project-card.tsx
│   │   ├── graph-stats.tsx
│   │   ├── agent-badge.tsx
│   │   ├── activity-feed.tsx
│   │   └── graph-query.tsx
│   └── lib/
│       ├── api.ts
│       └── use-websocket.ts
├── pyproject.toml        ← Python dependencies
├── package.json          ← Node dependencies
└── README.md
```

## Daemon Startup Flow

1. `agentic-os start` or `python -m daemon.main`
2. Initialize SQLite registry (create if not exists)
3. Start watchdog on `~/.agentic-os/inbox/`
4. Start FastAPI server on `localhost:8472`
5. Log: "Agentic OS ready. Watching ~/.agentic-os/inbox/"

## Agent Lifecycle

1. **Registration** — agent writes `register.json` to `inbox/<project>/`
2. **Graph build** — daemon runs full Graphify build on project codebase
3. **Heartbeat** — agent writes `heartbeat.json` every ~60s
4. **Contribution** — agent writes `finding-*.md` or `decision-*.md` as it discovers things
5. **Graph update** — daemon ingests findings, updates graph
6. **Deregistration** — agent stops writing heartbeats → marked offline after 5 min
7. **Re-registration** — agent writes new `register.json` → back online, graph live

## Error Handling

- **Malformed JSON** — logged, file moved to `.failed/`, error event pushed via WebSocket
- **Graphify build failure** — logged, retried once after 60s, then surfaced as error
- **Graphify import failure** — daemon logs warning, continues without graph features
- **Watchdog failure** — daemon exits with error code, logs the exception
- **Port conflict** — daemon logs which port is in use, suggests `--port` flag
- **Disk full** — watcher detects write errors, logs, continues monitoring (graceful degradation)

## Testing Strategy

- **Unit tests** — watcher, router, graph engine, registry (pytest)
- **Integration tests** — end-to-end: write inbox files, verify graph updates, query via API
- **Dashboard tests** — component rendering, WebSocket connectivity
- **Agent simulation** — test agent writing register/heartbeat/finding files

## Dependencies

### Python (daemon)
- `fastapi` + `uvicorn` — REST API + WebSocket
- `watchdog` — filesystem monitoring
- `graphify` (graphifyy) — knowledge graph engine
- `pydantic` — data validation
- `aiosqlite` — async SQLite

### Node.js (dashboard)
- `next` — React framework
- `shadcn/ui` — component library
- `tailwindcss` — styling
- `lucide-react` — icons

## Open Questions

- Should the daemon run as a launchd service (auto-start on login)?
- Should the dashboard support dark/light theme? (default: dark)
- Should there be a CLI tool (`agentic-os query "..."`) alongside the dashboard?
- Archive policy for `.processed/` files — keep forever? Rotate after N days?

## Out of Scope (v1)

- Multi-machine agent federation
- Agent-to-agent direct messaging
- Task dispatch from dashboard to specific agents
- Graphify visualization (HTML graph) in dashboard
- Authentication/authorization
- Payment/subscription integration
- Mobile dashboard
