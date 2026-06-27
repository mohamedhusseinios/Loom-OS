# API Reference

All endpoints on `http://localhost:8472`. CORS allows only `http://localhost:3000`.

## REST Endpoints

### Health & Discovery

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | Health check (daemon status, graphify availability, watcher running) |
| `GET` | `/api/discover?path=` | Browse filesystem directories for project discovery |

### Projects

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects` | List all tracked projects with node/edge/community/agent counts |
| `POST` | `/api/projects` | Create a tracked project (`{name, path}`) → 201 | 409 if exists |
| `GET` | `/api/projects/:id` | Project detail with graph stats and agent list |
| `DELETE` | `/api/projects/:id` | Remove a project from tracking |

### Graph

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/graph` | Graph stats only (nodes, edges, communities) |
| `GET` | `/api/projects/:id/graph/topology` | Full node/edge topology for visualization |
| `GET` | `/api/projects/:id/graph/communities` | Community list with sizes |
| `GET` | `/api/projects/:id/graph/flows` | Execution flows, ranked by criticality |
| `GET` | `/api/projects/:id/query?q=` | Natural language query of the knowledge graph |
| `POST` | `/api/projects/:id/rebuild` | Force a full graph rebuild |

### Agents

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/agents` | List agents with status and capabilities |

### Tasks & Dispatch

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/:id/dispatch` | Dispatch a task to an agent (`{target_agent, instruction, priority?}`) |
| `GET` | `/api/projects/:id/dispatches` | List recent task dispatches (newest first, max 50) |
| `GET` | `/api/projects/:id/tasks` | List all tasks for a project (supports status filter) |
| `POST` | `/api/projects/:id/tasks` | Create a task (`{title, assignee, body?, parents?, priority?}`) |
| `PATCH` | `/api/projects/:id/tasks/:taskId` | Update task status or metadata |
| `GET` | `/api/projects/:id/tasks/:taskId` | Get task detail |

### Context & Knowledge

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/:id/context` | Auto-generated shared context (graph stats, findings, agents) |

## WebSocket (`/ws`)

Single endpoint. Server pushes JSON events to all connected clients.

### Event Types

| Event | Payload | When |
|-------|---------|------|
| `agent:online` | `{agent, capabilities}` | Agent registers |
| `agent:dispatched` | `{task_id, target_agent, instruction}` | Task dispatched to agent |
| `graph:updated` | `{nodes_added, edges_added, communities, status, error?}` | Build/update completes |
| `finding:ingested` | `{file, type}` | Finding/decision processed |
| `project:created` | `{project_id, project_name}` | Project added |
| `project:deleted` | `{project_id}` | Project removed |
| `task:created` | `{task_id, project_id, assignee, status}` | Task created |
| `task:updated` | `{task_id, project_id, status}` | Task status changed |
| `task:completed` | `{task_id, project_id, summary}` | Worker finishes task |
| `error` | `{file, message}` | Processing failure |

> **Note:** There is no `agent:offline` event yet. `last_heartbeat` is recorded; a future sweep task will mark stale agents offline.

## Error Responses

| HTTP Status | Scenario |
|-------------|----------|
| 400 | Missing query param, invalid path, malformed input |
| 404 | Project not found |
| 409 | Duplicate project name |

All errors return `{"detail": "<message>"}`.
