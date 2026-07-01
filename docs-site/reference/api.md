# API reference

All endpoints are served by the daemon on `http://localhost:8472`. CORS allows only `http://localhost:3000` (the dashboard's origin). This page summarizes the key endpoints; the repository's full reference — every endpoint, request/response shape, and WebSocket event — lives in **[`docs/API.md`](https://github.com/mohamedhusseinios/Loom-OS/blob/main/docs/API.md)**.

## Health & discovery

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check (daemon status, graphify availability, watcher running) |
| `GET` | `/api/discover?path=` | Browse filesystem directories for project discovery |

## Projects

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects` | List all tracked projects with node/edge/community/agent counts |
| `POST` | `/api/projects` | Create a tracked project (`{name, path}`) → 201, 409 if it already exists |
| `GET` | `/api/projects/:id` | Project detail with graph stats and agent list |
| `DELETE` | `/api/projects/:id` | Remove a project from tracking |

## Graph

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/graph` | Graph stats only (nodes, edges, communities) |
| `GET` | `/api/projects/:id/graph/topology` | Full node/edge topology for visualization |
| `GET` | `/api/projects/:id/graph/communities` | Community list with sizes |
| `GET` | `/api/projects/:id/graph/flows` | Execution flows, ranked by criticality |
| `GET` | `/api/projects/:id/extracted-edges` | LLM-extracted (non-AST) edges for graph overlay |
| `GET` | `/api/projects/:id/query?q=` | Natural-language query of the knowledge graph |
| `POST` | `/api/projects/:id/rebuild` | Force a full graph rebuild |

See [The knowledge graph](../concepts/knowledge-graph.md) for how these are backed by `graphify-out/graph.json`.

## Search

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/search?q=&mode=text` | Text + vector search over findings (default) |
| `GET` | `/api/projects/:id/search?q=&mode=hybrid` | Graph + vector + relational search (vector-seeded BFS over AST + extracted edges) |

Full mechanics in [Hybrid search](../guides/hybrid-search.md).

## Agents

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/agents` | List agents with status and capabilities |
| `POST` | `/api/projects/:id/register-agent` | Register a coding agent (dual-write: inbox + immediate) |
| `DELETE` | `/api/projects/:id/agents/:agentId` | Remove an agent from a project |
| `GET` | `/api/agents/known` | Known agent types + which are installed on this machine |
| `GET` | `/api/agents/runnable` | Agents the daemon can spawn as workers |

## Tasks, dispatch & the task board

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/:id/dispatch` | Dispatch a task to an agent (`{target_agent, instruction, priority?}`) |
| `GET` | `/api/projects/:id/dispatches` | List recent task dispatches (newest first, max 50) |
| `GET` | `/api/projects/:id/tasks?status=` | List tasks for a project (optional status filter) |
| `POST` | `/api/projects/:id/tasks` | Create a task |
| `PATCH` | `/api/projects/:id/tasks/:taskId` | Update task status/assignee/result |
| `GET` | `/api/projects/:id/tasks/:taskId` | Get task detail |
| `POST` | `/api/projects/:id/tasks/:taskId/worker/start` | Manually start the worker for a task |
| `POST` | `/api/projects/:id/tasks/:taskId/worker/stop` | Stop a live worker |
| `GET` | `/api/projects/:id/tasks/:taskId/diff` | Git diff for a task's worktree branch |
| `POST` | `/api/projects/:id/tasks/:taskId/merge` | Merge a task's branch into a target |

## Context & knowledge

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/context` | Auto-generated shared context (graph stats, findings, agents) |
| `GET` | `/api/projects/:id/knowledge` | List knowledge sources discovered in the project |
| `POST` | `/api/projects/:id/knowledge/scan` | Scan and ingest all knowledge sources |

## WebSocket (`/ws`)

A single endpoint. The server pushes JSON events to every connected client — `agent:online`, `agent:offline`, `agent:dispatched`, `graph:updated`, `finding:ingested`, `extraction:completed`, `project:created`, `task:created`, `task:updated`, `task:completed`, `worker:started`, and more. Full event/payload table in [`docs/API.md`](https://github.com/mohamedhusseinios/Loom-OS/blob/main/docs/API.md#websocket-ws).

## Error responses

| HTTP status | Scenario |
|-------------|----------|
| 400 | Missing query param, invalid path, malformed input |
| 404 | Project not found |
| 409 | Duplicate project name |

All errors return `{"detail": "<message>"}`.

## See also

- [`docs/API.md`](https://github.com/mohamedhusseinios/Loom-OS/blob/main/docs/API.md) — the complete reference (every endpoint, all endpoint groups including evaluation, patterns, audit, temporal facts, and debugging/snapshots, not repeated here).
- [The filesystem protocol](../concepts/filesystem-protocol.md) — the write path most agents use instead of calling these APIs directly.
